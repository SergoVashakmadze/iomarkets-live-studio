from __future__ import annotations

import json

import httpx
import pytest
from conftest import Replay, load_recording
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from studio import ledger
from studio.ledger import BudgetExceeded, Ledger, asr_cost, response_cost
from studio.meta.responses import ResponsesClient
from studio.server import create_app

SCOUT = load_recording("scout_amd_2026-10-27.json")


def test_spark_cost_from_recorded_usage():
    body = SCOUT[1]["response"]  # 91,841 input (39,974 cached), 3,831 output, 7 searches
    expected = (91841 - 39974) * 1.25e-6 + 39974 * 0.15e-6 + 3831 * 4.25e-6 + 7 * 0.0025
    assert response_cost(body) == pytest.approx(expected)
    assert 0.10 < response_cost(body) < 0.11


def test_sam_cost_has_a_50_frame_minimum():
    assert response_cost({"usage": {"video_frames_processed": 300}}) == pytest.approx(0.06)
    assert response_cost({"usage": {"video_frames_processed": 10}}) == pytest.approx(0.01)


def test_asr_cost():
    assert asr_cost(3600) == pytest.approx(0.18)


def test_ledger_persists_and_caps(tmp_path):
    path = tmp_path / "l.json"
    a = Ledger(path, budget_usd=1.0)
    a.charge("spark", 0.4)
    a.charge("sam", 0.3)
    a.charge("spark", 0.0)  # nothing to record
    b = Ledger(path, budget_usd=1.0)  # a restart reads the same file
    assert b.today() == {"spark": 0.4, "sam": 0.3}
    b.check()
    b.charge("sam", 0.3)
    with pytest.raises(BudgetExceeded, match="resets at midnight UTC"):
        b.check()
    assert len(json.loads(path.read_text())) == 1  # one day


async def test_meta_calls_are_metered_and_fireworks_are_not(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "current", Ledger(tmp_path / "m.json"))
    replay = Replay([httpx.Response(200, json=SCOUT[1]["response"])] * 1)
    async with ResponsesClient(api_key="k", transport=replay.transport()) as meta:
        await meta.create_raw({"model": "muse-spark-1.3", "input": "x"})
    spent = ledger.current.today()["spark"]
    assert spent == pytest.approx(response_cost(SCOUT[1]["response"]), abs=1e-6)

    replay = Replay([httpx.Response(200, json=SCOUT[1]["response"])])
    fw = ResponsesClient(api_key="k", base_url="https://api.fireworks.ai/inference/v1",
                         transport=replay.transport())  # fmt: skip
    async with fw:
        await fw.create_raw({"model": "m", "input": "x"})
    assert list(ledger.current.today()) == ["spark"]  # unchanged


def test_server_refuses_new_work_over_budget(tmp_path):
    spend = Ledger(tmp_path / "s.json", budget_usd=0.5)
    spend.charge("sam", 0.6)
    app = create_app(editor_factory=lambda: None, spend=spend)
    http = TestClient(app)
    r = http.post("/api/brief", data={"subject": "Jane Doe, Example plc"})
    assert r.status_code == 429 and "budget" in r.json()["detail"]
    assert http.get("/api/budget").json()["spent_today_usd"] == pytest.approx(0.6)
    with http.websocket_connect("/ws/live") as ws:
        ws.send_json({"type": "start", "brief": "GUEST: x"})
        assert "budget" in ws.receive_json()["message"]
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 1008


def test_the_gpu_has_its_own_smaller_cap(tmp_path):
    from studio.ledger import Ledger, gpu_seconds

    book = Ledger(tmp_path / "l.json", budget_usd=10.0, gpu_budget_usd=1.0)
    assert book.gpu_allowed()
    book.charge("gpu", gpu_seconds(30 * 60))  # half an hour of GPU: ~$2.05
    assert not book.gpu_allowed()  # past the GPU cap: the anchor is shown still
    book.check()  # interviews themselves go on: the day's total is still under $10


def test_the_whole_day_budget_also_stops_the_gpu(tmp_path):
    from studio.ledger import Ledger

    book = Ledger(tmp_path / "l.json", budget_usd=2.0, gpu_budget_usd=5.0)
    book.charge("spark", 2.5)
    assert not book.gpu_allowed()

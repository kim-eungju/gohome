"""버스 → 1호선 환승 가능 여부 예상 테스트 (JNK → 가산 15분 가정, ±3분 이내 △)."""
from config import settings as cfg
from models.bus import BusArrival, BusStatus
from models.subway import GasanTrain
from services.transfer import Catch, judge

MIN = 60
RIDE = cfg.BUS_TO_GASAN_MIN * MIN


def _bus(sec, status=BusStatus.RUNNING, order=1):
    return BusArrival(order, status, sec, 3, "정류장", None, False, "")


def _train(remaining, at_station=False):
    g = GasanTrain("K1", "천안", False, None, None, None, None)
    g.remaining_sec, g.at_station = remaining, at_station
    return g


def test_ok_tight_miss():
    bus = _bus(4 * MIN)                       # 4분 후 버스 → 19분 후 가산
    at = 4 * MIN + RIDE
    assert judge(_train(at + 3 * MIN), bus) == Catch.OK        # 3분 이상 여유
    assert judge(_train(at + 3 * MIN - 1), bus) == Catch.TIGHT
    assert judge(_train(at), bus) == Catch.TIGHT
    assert judge(_train(at - 3 * MIN + 1), bus) == Catch.TIGHT  # 3분 이내로 늦음
    assert judge(_train(at - 3 * MIN), bus) == Catch.MISS


def test_arriving_soon_bus_counts_as_zero():
    assert judge(_train(RIDE + 5 * MIN), _bus(None, BusStatus.ARRIVING_SOON)) == Catch.OK


def test_unknown_bus_or_train_gives_none():
    for status in (BusStatus.WAITING, BusStatus.ENDED, BusStatus.NO_INFO):
        assert judge(_train(30 * MIN), _bus(None, status)) is None
    assert judge(_train(None), _bus(MIN)) is None


def test_train_at_gasan_is_miss():
    assert judge(_train(None, at_station=True), _bus(0, BusStatus.ARRIVING_SOON)) == Catch.MISS

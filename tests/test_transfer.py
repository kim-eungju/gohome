"""버스 → 1호선 환승 가능 여부 예상 테스트 (JNK → 가산 15분 가정)."""
from config import settings as cfg
from models.bus import BusArrival, BusStatus
from models.subway import TrainPosition
from services.transfer import Catch, judge

MIN = 60
RIDE = cfg.BUS_TO_GASAN_MIN * MIN


def _bus(sec, status=BusStatus.RUNNING, order=1):
    return BusArrival(order, status, sec, 3, "정류장", None, False, "")


def _train(away, est, age=0):
    return TrainPosition("T", "1001", "1", "", "구로", "천안", "1", False, False, None,
                         stations_away=away, age_sec=age, est_remaining_sec=est)


def test_ok_tight_miss():
    bus = _bus(4 * MIN)                       # 4분 후 버스 → 19분 후 가산
    at = 4 * MIN + RIDE
    assert judge(_train(9, at + 3 * MIN), bus) == Catch.OK        # 3분 이상 여유
    assert judge(_train(9, at + 3 * MIN - 1), bus) == Catch.TIGHT
    assert judge(_train(9, at), bus) == Catch.TIGHT
    assert judge(_train(9, at - 3 * MIN + 1), bus) == Catch.TIGHT  # 3분 이내로 늦음
    assert judge(_train(9, at - 3 * MIN), bus) == Catch.MISS


def test_arriving_soon_bus_counts_as_zero():
    assert judge(_train(7, RIDE + 5 * MIN), _bus(None, BusStatus.ARRIVING_SOON)) == Catch.OK


def test_unknown_bus_or_train_gives_none():
    for status in (BusStatus.WAITING, BusStatus.ENDED, BusStatus.NO_INFO):
        assert judge(_train(9, 30 * MIN), _bus(None, status)) is None
    assert judge(_train(None, None), _bus(MIN)) is None


def test_train_at_gasan_is_miss():
    assert judge(_train(0, None), _bus(0, BusStatus.ARRIVING_SOON)) == Catch.MISS


def test_far_train_uses_lower_bound():
    far = max(cfg.SUBWAY_TRAVEL_MIN_BY_STATIONS)
    # 표 최대값(32분) 이상 걸리는 열차 → 곧 오는 버스면 확실히 가능
    assert judge(_train(far + 3, None, age=30), _bus(2 * MIN)) == Catch.OK
    # 버스가 늦으면 판단 불가 (표시 안 함)
    assert judge(_train(far + 3, None, age=30), _bus(20 * MIN)) is None

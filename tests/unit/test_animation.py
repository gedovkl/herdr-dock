import pytest

from herdr_core.animation import AnimationConfig, Animator, Effect
from herdr_core.faces import AgentFace, EmptyFace, ExitFace, OfflineFace, PagerFace
from herdr_core.models import AgentStatus

S = AgentStatus


def face(status: AgentStatus) -> AgentFace:
    return AgentFace("claude", "x", status)


@pytest.mark.parametrize(
    ("status", "effect"),
    [
        (S.BLOCKED, Effect.BLINK),
        (S.WORKING, Effect.SPIN),
        (S.DONE, Effect.NONE),
        (S.IDLE, Effect.NONE),
        (S.UNKNOWN, Effect.NONE),
    ],
)
def test_default_agent_effects(status: AgentStatus, effect: Effect) -> None:
    assert Animator().effect(face(status)) is effect


def test_done_pulses_when_in_attention() -> None:
    animator = Animator(AnimationConfig(attention=frozenset({S.BLOCKED, S.DONE})))
    assert animator.effect(face(S.DONE)) is Effect.PULSE
    assert animator.effect(face(S.BLOCKED)) is Effect.BLINK


def test_working_does_not_spin_when_in_attention() -> None:
    animator = Animator(AnimationConfig(attention=frozenset({S.WORKING})))
    assert animator.effect(face(S.WORKING)) is Effect.PULSE


def test_summary_keys_follow_attention() -> None:
    animator = Animator(AnimationConfig(attention=frozenset({S.BLOCKED, S.DONE})))
    assert animator.effect(PagerFace(0, 2, (S.BLOCKED,))) is Effect.BLINK
    assert animator.effect(PagerFace(0, 2, (S.DONE, S.IDLE))) is Effect.PULSE
    assert animator.effect(ExitFace((S.IDLE,))) is Effect.NONE
    assert animator.effect(ExitFace((S.BLOCKED, S.DONE))) is Effect.BLINK
    assert animator.effect(EmptyFace()) is Effect.NONE
    assert animator.effect(OfflineFace()) is Effect.NONE


def test_disabled_animation() -> None:
    animator = Animator(AnimationConfig(enabled=False))
    assert animator.effect(face(S.BLOCKED)) is Effect.NONE
    assert animator.effect(face(S.WORKING)) is Effect.NONE


def test_frames_are_a_function_of_time() -> None:
    animator = Animator(AnimationConfig(blink_hz=2, spinner_fps=4, pulse_hz=0.5))
    assert [animator.frame(Effect.BLINK, t) for t in (0, 0.25, 0.5, 0.75)] == [0, 1, 0, 1]
    assert [animator.frame(Effect.SPIN, t) for t in (0, 0.25, 0.5, 0.75, 1.0)] == [0, 1, 2, 3, 0]
    assert [animator.frame(Effect.PULSE, t) for t in (0, 1, 2)] == [0, 1, 0]
    assert animator.frame(Effect.NONE, 12.3) == 0


def test_frame_counts_and_tick() -> None:
    assert [Animator.frame_count(e) for e in Effect] == [1, 4, 2, 2]
    assert Animator(AnimationConfig(blink_hz=2, spinner_fps=4)).tick_interval == 0.25
    assert Animator(AnimationConfig(blink_hz=5, spinner_fps=1)).tick_interval == 0.1


@pytest.mark.parametrize("name", ["blink_hz", "spinner_fps", "pulse_hz"])
def test_rates_must_be_positive(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        AnimationConfig(**{name: 0})

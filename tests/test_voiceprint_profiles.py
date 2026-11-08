"""Голос изменился, а перезаписать профиль было нельзя; и хранился только один голос."""
import numpy as np
import pytest

from justday import voiceprint


@pytest.fixture
def vp(tmp_path, monkeypatch):
    cfg = {"voiceprint": {"mode": "off", "profile": ""}}
    monkeypatch.setattr(voiceprint, "DIR", tmp_path / "vp")
    monkeypatch.setattr(voiceprint.config, "load", lambda: cfg)
    # тембр = средняя громкость клипа: разные голоса — разные вектора
    monkeypatch.setattr(voiceprint, "embed", lambda pcm: np.array([1.0, float(np.abs(pcm).mean())], dtype=np.float32))
    monkeypatch.setattr(voiceprint, "train_wake_verifier", lambda pos, neg: "")
    return cfg


def record(name, amp, phrases=3):
    voiceprint.begin(name)
    rng = np.random.default_rng(amp)
    for i in range(phrases):
        voiceprint.save_wav(voiceprint.draft(name) / f"phrase_{i}.wav", (rng.normal(0, amp, 16000)).astype(np.int16))


def test_rerecording_replaces_the_old_voice_entirely(vp):
    """Беда: новые записи ложились поверх старых, лишние клипы прежнего голоса оставались в профиле."""
    record("основной", 100, phrases=5)
    assert voiceprint.enroll_finish("основной")["clips"] == 5
    old = voiceprint.profile()["embedding"]
    record("основной", 3000, phrases=3)
    r = voiceprint.enroll_finish("основной")
    assert r["clips"] == 3
    assert voiceprint.profile()["embedding"] != old
    assert sorted(p.name for p in (voiceprint.DIR / "основной").glob("*.wav")) == [f"phrase_{i}.wav" for i in range(3)]


def test_failed_rerecording_keeps_the_old_profile(vp):
    """Брошенная на середине перезапись не должна стирать рабочий голос."""
    record("основной", 100)
    voiceprint.enroll_finish("основной")
    record("основной", 3000, phrases=1)
    assert not voiceprint.enroll_finish("основной")["ok"]
    assert voiceprint.profile() is not None


def test_several_voices_are_kept_and_the_active_one_switches(vp):
    record("я", 100)
    voiceprint.enroll_finish("я")
    record("простуженный", 3000)
    voiceprint.enroll_finish("простуженный")
    assert voiceprint.names() == ["простуженный", "я"]
    vp["voiceprint"]["profile"] = "я"
    a = voiceprint.profile()["embedding"]
    vp["voiceprint"]["profile"] = "простуженный"
    assert voiceprint.profile()["embedding"] != a
    voiceprint.reset("простуженный")
    assert voiceprint.names() == ["я"] and voiceprint.active() == "я"


def test_old_single_profile_survives_the_update(vp):
    """До обновления профиль лежал прямо в папке: после обновления голос не должен «пропасть»."""
    voiceprint.DIR.mkdir(parents=True)
    (voiceprint.DIR / "profile.json").write_text('{"embedding": [1, 0], "threshold": 0.5}')
    assert voiceprint.names() == [voiceprint.DEFAULT]
    assert voiceprint.profile()["threshold"] == 0.5


def test_profile_name_cannot_escape_the_folder(vp):
    with pytest.raises(ValueError):
        voiceprint.draft("../x")

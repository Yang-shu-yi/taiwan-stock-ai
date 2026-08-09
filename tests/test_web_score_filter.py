from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_exposes_all_three_score_light_filters() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'id="candidate-filter"' in html
    assert 'data-score-filter="green"' in html
    assert 'data-score-filter="yellow"' in html
    assert 'data-score-filter="red"' in html
    assert "function scoreLight(score)" in script
    assert 'scoreLight(item.score).key === activeCandidateFilter' in script


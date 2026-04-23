.PHONY: setup install test demo clean help

help:
	@echo "Prism — Claude Opus 4.7 as your music-video editor"
	@echo ""
	@echo "Targets:"
	@echo "  setup    Create venv + install system deps note"
	@echo "  install  Install Prism and Python deps (pip install -e .[dev])"
	@echo "  test     Run pytest"
	@echo "  demo     Run on examples/song.mp3 + examples/clips/"
	@echo "  clean    Remove caches + outputs"

setup:
	@command -v ffmpeg >/dev/null || (echo "Install ffmpeg: brew install ffmpeg" && exit 1)
	python3 -m venv .venv
	@echo "Activate: source .venv/bin/activate && make install"

install:
	pip install -e ".[dev,ui]"

test:
	pytest -q

assets:
	python scripts/make_sample_assets.py

demo:
	prism cut --song examples/song.mp3 --clips examples/clips --out out

dry:
	prism cut --song examples/song.mp3 --clips examples/clips --out out --dry

ui:
	streamlit run streamlit_app.py

smoke: assets dry

clean:
	rm -rf .prism-cache out build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +

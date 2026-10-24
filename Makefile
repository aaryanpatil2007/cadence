PY := .venv/bin/python
UV := uv

.PHONY: setup swift data enroll enroll-cli train daemon verify bank demo test collect

setup:
	$(UV) venv --python 3.11 --allow-existing
	$(UV) pip install -e .
	$(MAKE) swift || true
	$(MAKE) data
	$(PY) -m gait.attest.signer --smoke

swift:
	cd swift/gait-sign && swift build -c release

data:
	$(PY) scripts/fetch_cmu.py

enroll:
	$(PY) -m gait.daemon.app --enroll-open

enroll-cli:
	$(PY) -m gait.daemon.enroll --cli --profile $(PROFILE)

train:
	$(PY) -m gait.model.train
	$(PY) -m gait.model.calibrate

daemon:
	$(PY) -m gait.daemon.app

collect:
	$(PY) -m gait.daemon.app --collect

verify:
	$(PY) -m gait.verify.app

bank:
	$(PY) -m bank.app

demo:
	$(PY) demo/bot.py

test:
	$(PY) -m pytest tests/ -x -q

nessie-smoke:
	$(PY) -m bank.nessie

pretrain:
	$(PY) -m gait.model.pretrain

web:
	cd web/dashboard && npm install && npm run build
	cd web/bank && npm install && npm run build

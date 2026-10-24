.PHONY: ui test full

ui:
	python3 app.py

test:
	python3 -m unittest discover -s tests -t . -v

full:
	bash scripts/full-power.sh $(TARGET)

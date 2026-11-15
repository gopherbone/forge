PY ?= /opt/homebrew/bin/python3.12
GFORTRAN_LIB ?= /opt/homebrew/opt/gcc/lib/gcc/current
FREECAD_CCX ?= /Applications/FreeCAD.app/Contents/Resources/bin/ccx

.PHONY: setup tools test doctor clean

setup: .venv tools
	.venv/bin/pip install -q -e ".[test]"
	.venv/bin/forge doctor

.venv:
	$(PY) -m venv .venv
	.venv/bin/pip install -q --upgrade pip

# CalculiX: FreeCAD ships ccx but its libgfortran rpath is broken on macOS.
# Copy it (FreeCAD.app is not modified), add rpaths to Homebrew gcc + FreeCAD libs, ad-hoc re-sign.
tools: .tools/bin/ccx
.tools/bin/ccx:
	mkdir -p .tools/bin
	cp "$(FREECAD_CCX)" .tools/bin/ccx
	install_name_tool -add_rpath $(GFORTRAN_LIB) -add_rpath /Applications/FreeCAD.app/Contents/Resources/lib .tools/bin/ccx
	codesign -f -s - .tools/bin/ccx
	.tools/bin/ccx -v | tail -1

test:
	.venv/bin/python -m pytest -q

doctor:
	.venv/bin/forge doctor

clean:
	rm -rf projects/*/build

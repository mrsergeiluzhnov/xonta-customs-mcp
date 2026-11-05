#!/usr/bin/env bash
# Publish Xonta Customs RU: GitHub -> PyPI -> official MCP registry.
# Run from the project folder on your computer:  bash scripts/publish.sh
# Needs: gh (logged in as mrsergeiluzhnov), python3, a PyPI API token, mcp-publisher.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO=mrsergeiluzhnov/xonta-customs-mcp
VERSION=$(python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
echo "== version $VERSION"

# 1. GitHub
if ! gh repo view "$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --public --source . --push \
    --description "MCP server for importing into Russia/EAEU: invoices, TN VED codes, duties, VAT, fees, car recycling fee"
  gh repo edit "$REPO" --add-topic mcp,mcp-server,customs,tnved,eaeu,russia,import,hs-code,model-context-protocol
else
  git push origin main
fi
git tag -f "v$VERSION" && git push -f origin "v$VERSION"

# 2. PyPI (asks for the token: user __token__, password = pypi-...)
python3 -m pip install -q build twine
rm -rf dist && python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*

# 3. Official MCP registry (log in once first, see PUBLISHING.md step 4)
echo "== waiting for PyPI to show $VERSION"
for i in $(seq 1 30); do
  curl -sf "https://pypi.org/pypi/xonta-customs-mcp/$VERSION/json" >/dev/null && break
  sleep 10
done
mcp-publisher validate
mcp-publisher publish
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=ru.xonta/customs" | head -c 400; echo
echo "== done"

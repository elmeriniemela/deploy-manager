
## Prerequisite mermaid-cli installation:
* `sudo pacman -S nodejs npm`
* `sudo npm install -g @mermaid-js/mermaid-cli`
* `npx puppeteer browsers install chrome-headless-shell`

## Validate README.md diagram syntax:

* `awk '/```mermaid/{flag=1;next}/```/{flag=0}flag' README.md > docs/diagram.mmd`
* `mmdc -i docs/diagram.mmd -o docs/diagram.png`

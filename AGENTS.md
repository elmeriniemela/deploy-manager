
## Validate README.md diagram syntax:

* `awk '/```mermaid/{flag=1;next}/```/{flag=0}flag' README.md > docs/diagram.mmd`
* `mmdc -i docs/diagram.mmd -o docs/diagram.png`

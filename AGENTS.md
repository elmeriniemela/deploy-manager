
## Validate README.md diagram syntax:

* `mkdir build`
* `awk '/```mermaid/{flag=1;next}/```/{flag=0}flag' README.md > build/diagram.mmd`
* `mmdc -i build/diagram.mmd -o build/diagram.png`

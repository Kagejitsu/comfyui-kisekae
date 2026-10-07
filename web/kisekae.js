// comfyui-kisekae: read-only text box on the Prompt and Debug nodes.
// The stock front end only renders ui.text for its own "Preview as Text" node.
import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const DISPLAY_NODES = new Set(["KisekaePrompt", "KisekaeDebugJSON", "KisekaeDebugPrompt"]);
const WIDGET = "kisekae_display";

app.registerExtension({
    name: "kisekae.display",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!DISPLAY_NODES.has(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            const w = ComfyWidgets.STRING(this, WIDGET, ["STRING", { multiline: true }], app).widget;
            w.serialize = false; // display only: never saved into the workflow
            if (w.inputEl) {
                w.inputEl.readOnly = true;
                w.inputEl.placeholder = "Run the workflow to see output here";
                w.inputEl.style.fontFamily = "monospace";
                w.inputEl.style.fontSize = "11px";
                w.inputEl.style.opacity = 0.85;
            }
            return r;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const w = this.widgets?.find((x) => x.name === WIDGET);
            if (w && message?.text) w.value = message.text.join("");
        };
    },
});

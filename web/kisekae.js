// comfyui-kisekae: read-only text box on the Prompt, Debug and Save nodes.
// The stock front end only renders ui.text for its own "Preview as Text" node.
import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const DISPLAY_NODES = new Set(["KisekaePrompt", "KisekaeDebugJSON", "KisekaeDebugPrompt", "KisekaeSavePreset"]);
const WIDGET = "kisekae_display";

// Section nodes mark each field's typed text and append toggle as advanced inputs.
// The Vue renderer reads that from widget options; the canvas renderer (and its
// "Show Advanced" menu item) needs it on the widget itself.
const isAdvanced = (w) => w.options?.advanced;
const inUse = (w) => (typeof w.value === "string" ? w.value.trim() !== "" : w.value === true);

app.registerExtension({
    name: "kisekae.sections",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const inputs = Object.values(nodeData.input?.required ?? {});
        if (!nodeData.name.startsWith("Kisekae") || !inputs.some((spec) => spec[1]?.advanced)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            for (const w of this.widgets ?? []) if (isAdvanced(w)) w.advanced = true;
            this.setSize([this.size[0], this.computeSize()[1]]); // fit the visible rows only
            return r;
        };

        // Never hide an override that is in use: a node loaded with typed text or
        // "append" on opens its advanced inputs.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            if (!this.showAdvanced && this.widgets?.some((w) => isAdvanced(w) && inUse(w))) {
                this.showAdvanced = true;
                this.setSize([this.size[0], Math.max(this.size[1], this.computeSize()[1])]);
            }
            return r;
        };
    },
});

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

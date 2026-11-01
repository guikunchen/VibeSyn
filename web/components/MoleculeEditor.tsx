import { useMemo, useState } from "react";
import type { Ketcher } from "ketcher-core";
import { Editor } from "ketcher-react";
import { StandaloneStructServiceProvider } from "ketcher-standalone";

export default function MoleculeEditor() {
  const provider = useMemo(() => new StandaloneStructServiceProvider(), []);
  const [smiles, setSmiles] = useState("");

  const initialize = (ketcher: Ketcher) => {
    const editor = ketcher.editor as unknown as {
      subscribe: (event: string, callback: () => void) => void;
    };
    editor.subscribe("change", () => {
      void ketcher.getSmiles().then(setSmiles).catch(() => setSmiles(""));
    });
  };

  return (
    <div className="molecule-section">
      <div className="ketcher-frame">
        <Editor
          staticResourcesUrl=""
          structServiceProvider={provider}
          onInit={initialize}
          disableMacromoleculesEditor
        />
      </div>
      <label>
        Current molecule
        <code className="smiles-output">{smiles || "Draw a structure to generate SMILES."}</code>
      </label>
      <p className="field-help">The current workflow displays the molecule but does not attach it to the submitted task.</p>
    </div>
  );
}

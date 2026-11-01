import { useEffect, useState } from "react";
import initRDKitModule from "@rdkit/rdkit";

let rdkitPromise: ReturnType<typeof initRDKitModule> | null = null;

function rdkit() {
  if (!rdkitPromise) {
    rdkitPromise = initRDKitModule({
      locateFile: () => "/vendor/rdkit/RDKit_minimal.wasm",
    });
  }
  return rdkitPromise;
}

export default function MoleculeSvg({ smiles }: { smiles: string }) {
  const [svg, setSvg] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setSvg("");
    setFailed(false);
    void rdkit()
      .then((module) => {
        const molecule = module.get_mol(smiles);
        if (!molecule) throw new Error("Invalid SMILES");
        try {
          const next = molecule.get_svg(190, 115);
          if (active) setSvg(next);
        } finally {
          molecule.delete();
        }
      })
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [smiles]);
  if (failed) return <span className="bad-smiles">Invalid SMILES</span>;
  if (!svg) return <span className="mini-loader" />;
  return <div className="molecule-svg" dangerouslySetInnerHTML={{ __html: svg }} />;
}

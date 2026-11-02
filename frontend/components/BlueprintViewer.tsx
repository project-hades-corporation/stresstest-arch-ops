"use client";

import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from "@mui/material";
import { useMemo } from "react";
import CodeEditor from "react-simple-code-editor";
import Prism from "prismjs";
import "prismjs/components/prism-json";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-yaml";

import type { Blueprint } from "../src/types";

interface BlueprintModalProps {
  open: boolean;
  onClose: () => void;
  blueprint: Blueprint | null;
}

function highlight(code: string, lang: string): string {
  const grammar = Prism.languages[lang];
  if (!grammar) {
    return code.replace(/[&<>]/g, (character) => {
      switch (character) {
        case "&":
          return "&amp;";
        case "<":
          return "&lt;";
        default:
          return "&gt;";
      }
    });
  }
  return Prism.highlight(code, grammar, lang);
}

export default function BlueprintModal({ open, onClose, blueprint }: BlueprintModalProps) {
  const terraform = blueprint?.terraform_main ?? "";
  const variables = blueprint?.terraform_variables ?? "";
  const compose = blueprint?.docker_compose ?? "";
  const commands = blueprint?.setup_commands ?? [];

  const codeBlocks = useMemo(
    () => [
      { title: "Terraform main.tf", code: terraform, lang: "hcl" as string },
      { title: "Terraform variables.tf", code: variables, lang: "hcl" as string },
      { title: "Docker Compose", code: compose, lang: "yaml" as string },
      { title: "Setup Commands", code: commands.join("\n"), lang: "bash" as string },
    ],
    [terraform, variables, compose, commands]
  );

  const copy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      // clipboard unavailable
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Production Deployment Blueprint</DialogTitle>
      <DialogContent>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, mt: 1 }}>
          {codeBlocks.map((b) => (
            <Box key={b.title}>
              <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                {b.title}
              </Typography>
              <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, overflow: "hidden" }}>
                <CodeEditor
                  value={b.code}
                  highlight={(code) => highlight(code, b.lang)}
                  onValueChange={() => undefined}
                  readOnly
                  padding={12}
                  style={{
                    background: "#0d1117",
                    color: "#c9d1d9",
                    fontFamily: "monospace",
                    fontSize: "0.85rem",
                    lineHeight: 1.5,
                    minHeight: 160,
                    overflowY: "auto",
                    width: "100%",
                  }}
                />
              </Box>
              <Button size="small" onClick={() => void copy(b.code)}>
                Copy to clipboard
              </Button>
            </Box>
          ))}
          {blueprint?.notes ? <Typography variant="body2">{blueprint.notes}</Typography> : null}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

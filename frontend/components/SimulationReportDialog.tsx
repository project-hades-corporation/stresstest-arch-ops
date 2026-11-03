"use client";

import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from "@mui/material";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SimulationReport } from "../src/types";

interface SimulationReportDialogProps {
  open: boolean;
  onClose: () => void;
  report: SimulationReport | null;
}

function downloadReport(report: SimulationReport): void {
  const url = URL.createObjectURL(
    new Blob([report.markdown], { type: "text/markdown;charset=utf-8" })
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = report.path.split(/[\\/]/).pop() || "stress-report.md";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function SimulationReportDialog({
  open,
  onClose,
  report,
}: SimulationReportDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Detailed stress report</DialogTitle>
      <DialogContent>
        <Box sx={{ mb: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            Saved on the backend at <strong>{report?.path}</strong>. Reports are grouped
            by architecture name: re-running the same name replaces its file, while a
            new name creates a separate report.
          </Typography>
        </Box>
        <Box
          component="article"
          sx={{
            maxHeight: "65vh",
            overflow: "auto",
            m: 0,
            p: 2,
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 1,
            backgroundColor: "background.default",
            color: "text.primary",
            fontSize: "0.875rem",
            lineHeight: 1.65,
            "& h1, & h2, & h3, & h4": {
              mt: 2.5,
              mb: 1,
              lineHeight: 1.3,
            },
            "& h1": { mt: 0, fontSize: "1.5rem" },
            "& h2": {
              pb: 0.75,
              borderBottom: "1px solid",
              borderColor: "divider",
              fontSize: "1.2rem",
            },
            "& h3": { fontSize: "1rem" },
            "& p, & ul, & ol": { my: 1 },
            "& ul, & ol": { pl: 3 },
            "& li + li": { mt: 0.5 },
            "& table": {
              width: "100%",
              my: 1.5,
              borderCollapse: "collapse",
              fontSize: "0.8rem",
            },
            "& th, & td": {
              p: 1,
              border: "1px solid",
              borderColor: "divider",
              textAlign: "left",
              verticalAlign: "top",
            },
            "& th": { backgroundColor: "action.hover", fontWeight: 700 },
            "& code": {
              px: 0.5,
              borderRadius: 0.5,
              backgroundColor: "action.hover",
              fontFamily: "monospace",
              overflowWrap: "anywhere",
            },
            "& pre": {
              p: 1.5,
              overflowX: "auto",
              borderRadius: 1,
              backgroundColor: "action.hover",
            },
            "& pre code": { p: 0, backgroundColor: "transparent" },
            "& a": { color: "primary.light", overflowWrap: "anywhere" },
            "& blockquote": {
              ml: 0,
              pl: 2,
              borderLeft: "3px solid",
              borderColor: "divider",
              color: "text.secondary",
            },
            "& hr": { my: 2, border: 0, borderTop: "1px solid", borderColor: "divider" },
          }}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {report?.markdown ?? ""}
          </ReactMarkdown>
        </Box>
      </DialogContent>
      <DialogActions>
        {report ? (
          <Button
            startIcon={<DownloadOutlinedIcon />}
            onClick={() => downloadReport(report)}
          >
            Download Markdown
          </Button>
        ) : null}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

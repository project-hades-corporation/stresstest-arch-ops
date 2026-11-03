"use client";

import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  CircularProgress,
  Drawer,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import type { ScenarioType, StressScenarioRequest } from "../src/types";

const ARCHITECTURE_NAME_STORAGE_KEY = "stress-arch.architecture-name";

const SCENARIOS: Array<{
  id: ScenarioType;
  title: string;
  description: string;
}> = [
  {
    id: "traffic_surge",
    title: "Traffic Surge",
    description: "Estimate capacity at a higher request rate.",
  },
  {
    id: "database_outage",
    title: "Database Outage",
    description: "Drop database components and measure the graph impact.",
  },
  {
    id: "custom",
    title: "Custom Scenario",
    description: "Choose a load multiplier and optional failed nodes.",
  },
];

interface ScenarioDrawerProps {
  open: boolean;
  onClose: () => void;
  onRun: (scenario: StressScenarioRequest) => Promise<void>;
  running: boolean;
}

export default function ScenarioDrawer({ open, onClose, onRun, running }: ScenarioDrawerProps) {
  const [architectureName, setArchitectureName] = useState("");
  const [scenarioType, setScenarioType] = useState<ScenarioType>("traffic_surge");
  const [scenarioText, setScenarioText] = useState("");
  const [trafficMultiplier, setTrafficMultiplier] = useState("10");
  const [droppedNodes, setDroppedNodes] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const savedName = window.localStorage.getItem(ARCHITECTURE_NAME_STORAGE_KEY);
    if (savedName) setArchitectureName(savedName);
  }, []);

  const run = async () => {
    setError("");
    const trimmedArchitectureName = architectureName.trim();
    if (!trimmedArchitectureName) {
      setError("Enter an architecture name so its report can be saved.");
      return;
    }
    const multiplier = Number(trafficMultiplier);
    if (scenarioType !== "database_outage" && (!Number.isFinite(multiplier) || multiplier <= 0)) {
      setError("Enter a traffic multiplier greater than zero.");
      return;
    }
    if (scenarioType === "custom" && !scenarioText.trim()) {
      setError("Describe the custom failure scenario.");
      return;
    }

    try {
      window.localStorage.setItem(ARCHITECTURE_NAME_STORAGE_KEY, trimmedArchitectureName);
      await onRun({
        scenario_type: scenarioType,
        architecture_name: trimmedArchitectureName,
        scenario_text: scenarioText.trim() || undefined,
        traffic_multiplier: scenarioType === "database_outage" ? undefined : multiplier,
        baseline_rps: 100,
        dropped_nodes: droppedNodes
          .split(",")
          .map((nodeId) => nodeId.trim())
          .filter(Boolean),
      });
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "The simulation could not be completed.");
    }
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      slotProps={{ paper: { sx: { width: { xs: "100%", sm: 370 }, p: 3 } } }}
    >
      <Stack spacing={2.5}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Run a simulation
          </Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
            Deterministic estimates from your current canvas.
          </Typography>
        </Box>

        <Stack spacing={1}>
          <Typography variant="overline" color="text.secondary">
            Architecture
          </Typography>
          <TextField
            label="Architecture name"
            placeholder="e.g. Payments platform"
            value={architectureName}
            onChange={(event) => setArchitectureName(event.target.value)}
            helperText="Re-running this name replaces its report; a new name creates a new report file."
            disabled={running}
            required
          />
        </Stack>

        <Stack spacing={1}>
          {SCENARIOS.map((scenario) => (
            <Card
              key={scenario.id}
              variant="outlined"
              sx={{
                borderColor: scenarioType === scenario.id ? "primary.main" : "divider",
                backgroundColor: scenarioType === scenario.id ? "action.selected" : "transparent",
              }}
            >
              <CardActionArea disabled={running} onClick={() => setScenarioType(scenario.id)}>
                <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
                  <Typography sx={{ fontWeight: 650 }}>{scenario.title}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {scenario.description}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          ))}
        </Stack>

        {scenarioType === "traffic_surge" ? (
          <TextField
            label="Traffic multiplier"
            type="number"
            value={trafficMultiplier}
            onChange={(event) => setTrafficMultiplier(event.target.value)}
            slotProps={{ htmlInput: { min: 0.01, step: 0.5 } }}
            helperText="10 means ten times the 100 RPS baseline."
            disabled={running}
          />
        ) : null}

        {scenarioType === "database_outage" ? (
          <Alert severity="info">
            Database nodes on the canvas will be marked unavailable automatically.
          </Alert>
        ) : null}

        {scenarioType === "custom" ? (
          <>
            <TextField
              label="Scenario description"
              placeholder="e.g. Redis outage during a traffic surge"
              value={scenarioText}
              onChange={(event) => setScenarioText(event.target.value)}
              multiline
              minRows={2}
              disabled={running}
            />
            <TextField
              label="Traffic multiplier"
              type="number"
              value={trafficMultiplier}
              onChange={(event) => setTrafficMultiplier(event.target.value)}
              slotProps={{ htmlInput: { min: 0.01, step: 0.5 } }}
              disabled={running}
            />
            <TextField
              label="Failed node IDs (optional)"
              placeholder="database_primary, cache"
              value={droppedNodes}
              onChange={(event) => setDroppedNodes(event.target.value)}
              helperText="Separate IDs with commas."
              disabled={running}
            />
          </>
        ) : null}

        {error ? <Alert severity="error">{error}</Alert> : null}

        <Button
          variant="contained"
          size="large"
          onClick={() => void run()}
          disabled={running}
          startIcon={running ? <CircularProgress size={18} color="inherit" /> : undefined}
        >
          {running ? "Simulating..." : "Run simulation"}
        </Button>
      </Stack>
    </Drawer>
  );
}

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import {
  CheckCircle,
  XCircle,
  Clock,
  Trash2,
  Download,
  RefreshCw,
  Settings,
  Search,
  Loader2,
  User,
  Moon,
  Sun,
} from "lucide-react";

import MapSelector from "./components/MapSelector";
import JobResultsPanel from "./components/JobResultsPanel";
import type {
  JobInfo,
  MachineProfile,
  MaterialProfile,
  PipelineConfig,
  ProfileDefaultsResponse,
  AuthResponse,
  AuthUser,
  CustomProfilesResponse,
} from "./types";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const GEOCODE_URL =
  import.meta.env.VITE_GEOCODE_URL ??
  "https://nominatim.openstreetmap.org/search";
const COORD_DECIMALS = 5;
const AUTH_TOKEN_KEY = "elevation-relief.authToken.v1";

const FALLBACK_MACHINE_PROFILES: MachineProfile[] = [
  {
    id: "cricut-maker-3",
    name: "Cricut Maker 3",
    bed_width_in: 12,
    bed_height_in: 12,
    sheet_margin_in: 0.25,
    sheet_gap_in: 0.08,
    calibration_enabled_default: false,
  },
  {
    id: "laser-cutter",
    name: "Laser Cutter",
    bed_width_in: 24,
    bed_height_in: 12,
    sheet_margin_in: 0.25,
    sheet_gap_in: 0.125,
    calibration_enabled_default: true,
  },
];

const FALLBACK_MATERIAL_PROFILES: MaterialProfile[] = [
  {
    id: "birch-1-4-12x24",
    name: '1/4" Birch (12x24)',
    sheet_width_in: 24,
    sheet_height_in: 12,
    layer_thickness_mm: 6.35,
  },
  {
    id: "birch-1-8-12x24",
    name: '1/8" Birch (12x24)',
    sheet_width_in: 24,
    sheet_height_in: 12,
    layer_thickness_mm: 3.175,
  },
  {
    id: "birch-1-16-12x12",
    name: '1/16" Birch (12x12)',
    sheet_width_in: 12,
    sheet_height_in: 12,
    layer_thickness_mm: 1.5875,
  },
  {
    id: "paper-0p004-letter",
    name: 'Paper 0.004" (Letter 8.5x11)',
    sheet_width_in: 11,
    sheet_height_in: 8.5,
    layer_thickness_mm: 0.1016,
  },
];

const DEFAULT_CONFIG: PipelineConfig = {
  experiment: { name: "web_run_01", output_dir: "results" },
  region: {
    center_lat: 44.02383819213837,
    center_lon: -71.83153152465822,
    radius_m: 2000,
  },
  model: {
    width_inches: 5.0,
    height_inches: 5.0,
    layer_thickness_mm: 3.175,
    contour_interval_m: 50.0,
  },
  data: {
    dem_source: "glo_30",
    imagery_source: "naip",
    imagery_resolution: "5m",
  },
  profiles: {
    machine_id: "laser-cutter",
    machine_name: "Laser Cutter",
    material_id: "birch-1-8-12x24",
    material_name: '1/8" Birch (12x24)',
  },
  processing: {
    smoothing_sigma: 0.0,
    simplification_tol: 0.5,
    kerf_width_mm: 0.15,
    geometric_smoothing: false,
    texture_normalize: true,
    texture_normalize_cutoff: 1.0,
    texture_gamma: 1.1,
    min_part_area_sq_in: 0.015,
    calibration: {
      enabled: true,
      mode: "auto_pack",
      pattern: "gamma_ladder",
      gamma_min: 0.7,
      gamma_max: 1.6,
      gamma_steps: 10,
      strip_width_mm: 140,
      strip_height_mm: 28,
      padding_mm: 2,
    },
    nesting: {
      enabled: true,
      sheet_width_in: 24.0,
      sheet_height_in: 12.0,
      bed_width_in: 24.0,
      bed_height_in: 12.0,
      sheet_margin_in: 0.25,
      sheet_gap_in: 0.125,
    },
  },
  export: { format: "dxf", layers_per_file: 1 },
};

function formatTime(isoString: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function getStatusIcon(status: string) {
  switch (status) {
    case "completed":
      return <CheckCircle className="h-4 w-4 text-chart-5" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-destructive" />;
    case "canceled":
      return <XCircle className="h-4 w-4 text-muted-foreground" />;
    case "running":
      return <RefreshCw className="h-4 w-4 text-primary animate-spin" />;
    case "pending":
      return <Clock className="h-4 w-4 text-accent" />;
    default:
      return null;
  }
}

function getStatusBadge(status: string) {
  switch (status) {
    case "completed":
      return <Badge variant="success">Completed</Badge>;
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
    case "canceled":
      return <Badge variant="outline">Cancelled</Badge>;
    case "running":
      return <Badge variant="processing">Running</Badge>;
    case "pending":
      return <Badge variant="warning">Pending</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

/* ---------- helpers for flat form state ---------- */

function useFormState<T extends Record<string, unknown>>(initial: T) {
  const [state, setState] = useState(initial);

  const set = (path: string, value: unknown) => {
    setState((prev) => {
      const copy = structuredClone(prev) as Record<string, unknown>;
      const keys = path.split(".");
      let cur = copy;
      for (let i = 0; i < keys.length - 1; i++) {
        if (cur[keys[i]] === undefined || cur[keys[i]] === null) {
          cur[keys[i]] = {};
        }
        cur = cur[keys[i]] as Record<string, unknown>;
      }
      cur[keys[keys.length - 1]] = value;
      return copy as T;
    });
  };

  const get = (path: string): unknown => {
    const keys = path.split(".");
    let cur: unknown = state;
    for (const k of keys) {
      if (cur === undefined || cur === null) return undefined;
      cur = (cur as Record<string, unknown>)[k];
    }
    return cur;
  };

  const setMany = (updates: Record<string, unknown>) => {
    setState((prev) => {
      const copy = structuredClone(prev) as Record<string, unknown>;
      for (const [path, value] of Object.entries(updates)) {
        const keys = path.split(".");
        let cur = copy;
        for (let i = 0; i < keys.length - 1; i++) {
          if (cur[keys[i]] === undefined || cur[keys[i]] === null) {
            cur[keys[i]] = {};
          }
          cur = cur[keys[i]] as Record<string, unknown>;
        }
        cur[keys[keys.length - 1]] = value;
      }
      return copy as T;
    });
  };

  return { state, set, get, setMany, setState };
}

/* ==================== FormField component ==================== */

function FormField({
  label,
  htmlFor,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <Label htmlFor={htmlFor} className="mb-1.5 block text-sm">
        {label}
      </Label>
      {children}
      {hint && (
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

/* ==================== NumberInput wrapper ==================== */

function NumberInput({
  value,
  onChange,
  step,
  min,
  max,
  disabled,
  id,
  className,
  formatter,
}: {
  value: number | undefined;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  disabled?: boolean;
  id?: string;
  className?: string;
  formatter?: (v: number) => string;
}) {
  const displayValue = value !== undefined && formatter ? formatter(value) : value ?? "";
  return (
    <Input
      id={id}
      type="number"
      value={displayValue}
      onChange={(e) => {
        const v = parseFloat(e.target.value);
        if (Number.isFinite(v)) onChange(v);
      }}
      step={step}
      min={min}
      max={max}
      disabled={disabled}
      className={className}
    />
  );
}

/* ==================== Main App ==================== */

function App() {
  const form = useFormState(DEFAULT_CONFIG as unknown as Record<string, unknown>);
  const config = form.state as unknown as PipelineConfig;

  const queryClient = useQueryClient();
  const [expandedJobs, setExpandedJobs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState("map");
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [customMachineProfiles, setCustomMachineProfiles] = useState<MachineProfile[]>([]);
  const [customMaterialProfiles, setCustomMaterialProfiles] = useState<MaterialProfile[]>([]);
  const [machineProfileNameInput, setMachineProfileNameInput] = useState("");
  const [materialProfileNameInput, setMaterialProfileNameInput] = useState("");
  const [authToken, setAuthToken] = useState<string | null>(() =>
    localStorage.getItem(AUTH_TOKEN_KEY)
  );
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const lastEditedRef = useRef<"radius" | "contour">("radius");
  const isInternalUpdate = useRef(false);

  // Dark mode class toggle
  useEffect(() => {
    const root = document.getElementById("root");
    if (root) {
      if (isDarkMode) {
        root.classList.add("dark");
      } else {
        root.classList.remove("dark");
      }
    }
  }, [isDarkMode]);

  // Derived form values
  const lat = (config.region.center_lat ?? DEFAULT_CONFIG.region.center_lat) as number;
  const lon = (config.region.center_lon ?? DEFAULT_CONFIG.region.center_lon) as number;
  const radius = (config.region.radius_m ?? DEFAULT_CONFIG.region.radius_m) as number;
  const widthIn = (config.model.width_inches ?? DEFAULT_CONFIG.model.width_inches) as number;
  const heightIn = (config.model.height_inches ?? DEFAULT_CONFIG.model.height_inches) as number;
  const thicknessMm = (config.model.layer_thickness_mm ?? DEFAULT_CONFIG.model.layer_thickness_mm) as number;
  const contourInterval = (config.model.contour_interval_m ?? DEFAULT_CONFIG.model.contour_interval_m) as number;
  const selectedMachineProfileId = (config.profiles.machine_id ?? DEFAULT_CONFIG.profiles.machine_id) as string;
  const selectedMaterialProfileId = (config.profiles.material_id ?? DEFAULT_CONFIG.profiles.material_id) as string;
  const bedWidthIn = config.processing.nesting.bed_width_in;
  const bedHeightIn = config.processing.nesting.bed_height_in;
  const sheetWidthIn = config.processing.nesting.sheet_width_in;
  const sheetHeightIn = config.processing.nesting.sheet_height_in;
  const sheetMarginIn = config.processing.nesting.sheet_margin_in;
  const sheetGapIn = config.processing.nesting.sheet_gap_in;
  const calibrationEnabled = config.processing.calibration.enabled;

  const formatCoord = (value: number) => {
    if (!Number.isFinite(value)) return "";
    const factor = 10 ** COORD_DECIMALS;
    const truncated = Math.trunc(value * factor) / factor;
    return truncated.toFixed(COORD_DECIMALS);
  };

  // ---- heartbeat ----
  useEffect(() => {
    let isActive = true;
    const ping = async () => {
      try {
        await fetch(`${API_URL}/`, { cache: "no-store" });
      } catch (_) {
        /* ignore */
      }
    };
    const startHeartbeat = () => {
      if (!isActive) return;
      ping();
    };
    startHeartbeat();
    const intervalId = window.setInterval(startHeartbeat, 9 * 60 * 1000);
    return () => {
      isActive = false;
      window.clearInterval(intervalId);
    };
  }, []);

  // ---- Profile defaults ----
  const { data: profileDefaults } = useQuery({
    queryKey: ["profileDefaults"],
    queryFn: async () => {
      const res = await axios.get(`${API_URL}/profiles/defaults`);
      return res.data as ProfileDefaultsResponse;
    },
    staleTime: 30 * 60 * 1000,
  });

  const builtInMachineProfiles =
    profileDefaults?.machine_profiles ?? FALLBACK_MACHINE_PROFILES;
  const builtInMaterialProfiles =
    profileDefaults?.material_profiles ?? FALLBACK_MATERIAL_PROFILES;

  // ---- Auth persistence ----
  useEffect(() => {
    if (authToken) localStorage.setItem(AUTH_TOKEN_KEY, authToken);
    else localStorage.removeItem(AUTH_TOKEN_KEY);
  }, [authToken]);

  const authHeaders = useMemo(
    () => (authToken ? { Authorization: `Bearer ${authToken}` } : undefined),
    [authToken]
  );

  // ---- Auth queries ----
  const authMeQuery = useQuery({
    queryKey: ["authMe", authToken],
    queryFn: async () => {
      if (!authHeaders) return null;
      const res = await axios.get(`${API_URL}/auth/me`, {
        headers: authHeaders,
      });
      return res.data as AuthUser;
    },
    enabled: !!authToken,
    retry: false,
  });

  const customProfilesQuery = useQuery({
    queryKey: ["customProfiles", authToken],
    queryFn: async () => {
      if (!authHeaders) return null;
      const res = await axios.get(`${API_URL}/profiles/custom`, {
        headers: authHeaders,
      });
      return res.data as CustomProfilesResponse;
    },
    enabled: !!authToken,
    retry: false,
  });
  const { refetch: refetchCustomProfiles, isFetching: isCustomProfilesLoading } =
    customProfilesQuery;

  useEffect(() => {
    if (authMeQuery.data) setAuthUser(authMeQuery.data);
  }, [authMeQuery.data]);
  useEffect(() => {
    if (authMeQuery.isError) {
      setAuthToken(null);
      setAuthUser(null);
    }
  }, [authMeQuery.isError]);
  useEffect(() => {
    if (customProfilesQuery.data) {
      setCustomMachineProfiles(customProfilesQuery.data.machine_profiles ?? []);
      setCustomMaterialProfiles(
        customProfilesQuery.data.material_profiles ?? []
      );
    }
  }, [customProfilesQuery.data]);
  useEffect(() => {
    if (customProfilesQuery.isError) {
      setCustomMachineProfiles([]);
      setCustomMaterialProfiles([]);
    }
  }, [customProfilesQuery.isError]);
  useEffect(() => {
    if (!authToken) {
      setAuthUser(null);
      setCustomMachineProfiles([]);
      setCustomMaterialProfiles([]);
    }
  }, [authToken]);

  const machineProfiles = useMemo(
    () => [...builtInMachineProfiles, ...customMachineProfiles],
    [builtInMachineProfiles, customMachineProfiles]
  );
  const materialProfiles = useMemo(
    () => [...builtInMaterialProfiles, ...customMaterialProfiles],
    [builtInMaterialProfiles, customMaterialProfiles]
  );

  // ---- Profile application ----
  const applyMachineProfile = (profile: MachineProfile) => {
    form.setMany({
      "profiles.machine_id": profile.id,
      "profiles.machine_name": profile.name,
      "processing.nesting.bed_width_in": profile.bed_width_in,
      "processing.nesting.bed_height_in": profile.bed_height_in,
      "processing.nesting.sheet_margin_in": profile.sheet_margin_in,
      "processing.nesting.sheet_gap_in": profile.sheet_gap_in,
      "processing.calibration.enabled": profile.calibration_enabled_default,
    });
  };

  const applyMaterialProfile = (profile: MaterialProfile) => {
    form.setMany({
      "profiles.material_id": profile.id,
      "profiles.material_name": profile.name,
      "model.layer_thickness_mm": profile.layer_thickness_mm,
      "processing.nesting.sheet_width_in": profile.sheet_width_in,
      "processing.nesting.sheet_height_in": profile.sheet_height_in,
    });
  };

  const handleMachineProfileSelect = (profileId: string) => {
    const profile = machineProfiles.find((item) => item.id === profileId);
    if (profile) applyMachineProfile(profile);
  };

  const handleMaterialProfileSelect = (profileId: string) => {
    const profile = materialProfiles.find((item) => item.id === profileId);
    if (profile) applyMaterialProfile(profile);
  };

  const selectedMachineIsCustom = !!selectedMachineProfileId?.startsWith(
    "custom-machine-"
  );
  const selectedMaterialIsCustom = !!selectedMaterialProfileId?.startsWith(
    "custom-material-"
  );

  // ---- Profile save/delete ----
  const saveMachineProfile = async () => {
    if (!authHeaders) {
      setAuthError("Please login to save profiles.");
      return;
    }
    const existing = machineProfiles.find(
      (item) => item.id === selectedMachineProfileId
    );
    const name =
      machineProfileNameInput.trim() || existing?.name || "Custom Machine";
    const payload = {
      kind: "machine",
      name,
      data: {
        bed_width_in: Number(bedWidthIn),
        bed_height_in: Number(bedHeightIn),
        sheet_margin_in: Number(sheetMarginIn),
        sheet_gap_in: Number(sheetGapIn),
        calibration_enabled_default: Boolean(calibrationEnabled),
      },
    };
    try {
      if (
        selectedMachineIsCustom &&
        !machineProfileNameInput.trim() &&
        selectedMachineProfileId
      ) {
        await axios.put(
          `${API_URL}/profiles/custom/${selectedMachineProfileId}`,
          payload,
          { headers: authHeaders }
        );
      } else {
        await axios.post(`${API_URL}/profiles/custom`, payload, {
          headers: authHeaders,
        });
      }
      setAuthError(null);
      setMachineProfileNameInput("");
      await refetchCustomProfiles();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setAuthError(
        err?.response?.data?.detail ?? "Unable to save machine profile."
      );
    }
  };

  const saveMaterialProfile = async () => {
    if (!authHeaders) {
      setAuthError("Please login to save profiles.");
      return;
    }
    const existing = materialProfiles.find(
      (item) => item.id === selectedMaterialProfileId
    );
    const name =
      materialProfileNameInput.trim() || existing?.name || "Custom Material";
    const payload = {
      kind: "material",
      name,
      data: {
        sheet_width_in: Number(sheetWidthIn),
        sheet_height_in: Number(sheetHeightIn),
        layer_thickness_mm: Number(thicknessMm),
      },
    };
    try {
      if (
        selectedMaterialIsCustom &&
        !materialProfileNameInput.trim() &&
        selectedMaterialProfileId
      ) {
        await axios.put(
          `${API_URL}/profiles/custom/${selectedMaterialProfileId}`,
          payload,
          { headers: authHeaders }
        );
      } else {
        await axios.post(`${API_URL}/profiles/custom`, payload, {
          headers: authHeaders,
        });
      }
      setAuthError(null);
      setMaterialProfileNameInput("");
      await refetchCustomProfiles();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setAuthError(
        err?.response?.data?.detail ?? "Unable to save material profile."
      );
    }
  };

  const deleteSelectedCustomMachineProfile = async () => {
    if (!authHeaders || !selectedMachineProfileId || !selectedMachineIsCustom)
      return;
    try {
      await axios.delete(
        `${API_URL}/profiles/custom/${selectedMachineProfileId}`,
        { headers: authHeaders, params: { kind: "machine" } }
      );
      setAuthError(null);
      await refetchCustomProfiles();
      const fallback =
        builtInMachineProfiles.find(
          (item) => item.id === DEFAULT_CONFIG.profiles.machine_id
        ) ?? builtInMachineProfiles[0];
      if (fallback) applyMachineProfile(fallback);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setAuthError(
        err?.response?.data?.detail ?? "Unable to delete machine profile."
      );
    }
  };

  const deleteSelectedCustomMaterialProfile = async () => {
    if (
      !authHeaders ||
      !selectedMaterialProfileId ||
      !selectedMaterialIsCustom
    )
      return;
    try {
      await axios.delete(
        `${API_URL}/profiles/custom/${selectedMaterialProfileId}`,
        { headers: authHeaders, params: { kind: "material" } }
      );
      setAuthError(null);
      await refetchCustomProfiles();
      const fallback =
        builtInMaterialProfiles.find(
          (item) => item.id === DEFAULT_CONFIG.profiles.material_id
        ) ?? builtInMaterialProfiles[0];
      if (fallback) applyMaterialProfile(fallback);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setAuthError(
        err?.response?.data?.detail ?? "Unable to delete material profile."
      );
    }
  };

  // ---- Auth mutations ----
  const signup = useMutation({
    mutationFn: async () => {
      const res = await axios.post(`${API_URL}/auth/signup`, {
        email: authEmail,
        password: authPassword,
      });
      return res.data as AuthResponse;
    },
    onSuccess: (data) => {
      setAuthToken(data.token);
      setAuthUser(data.user);
      setAuthError(null);
      setAuthPassword("");
      queryClient.invalidateQueries({ queryKey: ["customProfiles"] });
      queryClient.invalidateQueries({ queryKey: ["allJobs"] });
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } } };
      setAuthError(err?.response?.data?.detail ?? "Signup failed.");
    },
  });

  const login = useMutation({
    mutationFn: async () => {
      const res = await axios.post(`${API_URL}/auth/login`, {
        email: authEmail,
        password: authPassword,
      });
      return res.data as AuthResponse;
    },
    onSuccess: (data) => {
      setAuthToken(data.token);
      setAuthUser(data.user);
      setAuthError(null);
      setAuthPassword("");
      queryClient.invalidateQueries({ queryKey: ["customProfiles"] });
      queryClient.invalidateQueries({ queryKey: ["allJobs"] });
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } } };
      setAuthError(err?.response?.data?.detail ?? "Login failed.");
    },
  });

  const handleLogout = async () => {
    try {
      if (authHeaders) {
        await axios.post(`${API_URL}/auth/logout`, {}, { headers: authHeaders });
      }
    } catch (_) {
      /* ignore */
    }
    setAuthToken(null);
    setAuthUser(null);
    setCustomMachineProfiles([]);
    setCustomMaterialProfiles([]);
    queryClient.invalidateQueries({ queryKey: ["allJobs"] });
  };

  // ---- Job mutations ----
  const submitJob = useMutation({
    mutationFn: async (values: PipelineConfig) => {
      if (!authHeaders) throw new Error("Please login to submit jobs.");
      const res = await axios.post(`${API_URL}/jobs`, values, {
        headers: authHeaders,
      });
      return res.data as JobInfo;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["allJobs"] });
      setActiveTab("jobs");
    },
  });

  const cancelJob = useMutation({
    mutationFn: async (jobId: string) => {
      if (!authHeaders) throw new Error("Please login.");
      const res = await axios.post(
        `${API_URL}/jobs/${jobId}/cancel`,
        {},
        { headers: authHeaders }
      );
      return res.data as { status: string; message: string };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["allJobs"] });
    },
  });

  const deleteJob = useMutation({
    mutationFn: async (jobId: string) => {
      if (!authHeaders) throw new Error("Please login.");
      const res = await axios.delete(`${API_URL}/jobs/${jobId}`, {
        headers: authHeaders,
      });
      return res.data;
    },
    onSuccess: (_, jobId) => {
      setExpandedJobs((prev) => prev.filter((id) => id !== jobId));
      queryClient.invalidateQueries({ queryKey: ["allJobs"] });
    },
  });

  const handleDeleteJob = (jobId: string) => {
    deleteJob.mutate(jobId);
  };

  // ---- Jobs query ----
  const { data: allJobs, isError: allJobsError } = useQuery({
    queryKey: ["allJobs", authToken],
    queryFn: async () => {
      if (!authHeaders) return {};
      const res = await axios.get(`${API_URL}/jobs`, {
        headers: authHeaders,
      });
      return res.data as Record<string, JobInfo>;
    },
    enabled: !!authToken,
    refetchInterval: (query) => {
      const jobs = query.state.data as Record<string, JobInfo> | undefined;
      const ids = Object.keys(jobs || {});
      if (!jobs || ids.length === 0) return 2000;
      const hasRunning = ids.some((id) => {
        const job = jobs[id];
        return job && (job.status === "running" || job.status === "pending");
      });
      return hasRunning ? 2000 : false;
    },
  });

  const jobHistory = useMemo(() => {
    const entries = Object.entries(allJobs || {});
    entries.sort((a, b) => {
      const aTime = new Date(a[1].created_at || 0).getTime();
      const bTime = new Date(b[1].created_at || 0).getTime();
      return bTime - aTime;
    });
    return entries.map(([id]) => id);
  }, [allJobs]);

  useEffect(() => {
    if (allJobs && jobHistory.length > 0) {
      const latestJob = allJobs[jobHistory[0]];
      if (latestJob?.status === "completed") {
        setExpandedJobs((prev) =>
          prev.includes(latestJob.id) ? prev : [latestJob.id, ...prev]
        );
        setActiveTab("jobs");
      }
    }
  }, [allJobs, jobHistory]);

  const normalizeLongitude = (lonVal: number) => {
    const wrapped = (((lonVal + 180) % 360) + 360) % 360 - 180;
    if (Object.is(wrapped, -180)) return 180;
    return wrapped;
  };

  const handleMapCoords = (newLat: number, newLon: number) => {
    lastEditedRef.current = "radius";
    form.setMany({
      "region.center_lat": newLat,
      "region.center_lon": normalizeLongitude(newLon),
    });
  };

  const handleSearchLocation = async (query: string) => {
    if (!query.trim()) return;
    setSearchLoading(true);
    setSearchError(null);
    try {
      const params = new URLSearchParams({
        format: "json",
        q: query.trim(),
        limit: "1",
      });
      const res = await fetch(`${GEOCODE_URL}?${params.toString()}`, {
        headers: { "Accept-Language": "en" },
      });
      if (!res.ok) throw new Error(`Search failed (${res.status})`);
      const data = await res.json();
      if (!Array.isArray(data) || data.length === 0) {
        setSearchError("No results found. Try a different query.");
        return;
      }
      const result = data[0];
      const newLat = Number(result.lat);
      const newLon = Number(result.lon);
      if (!Number.isFinite(newLat) || !Number.isFinite(newLon)) {
        setSearchError("Search returned invalid coordinates.");
        return;
      }
      handleMapCoords(newLat, newLon);
      setActiveTab("map");
    } catch (_) {
      setSearchError("Unable to search location. Please try again.");
    } finally {
      setSearchLoading(false);
    }
  };

  // ---- Radius / contour coupling ----
  useEffect(() => {
    if (isInternalUpdate.current) return;
    if (!widthIn || !radius || !thicknessMm) return;

    const widthMm = widthIn * 25.4;
    const scaleMmPerM = widthMm / (2 * radius);

    if (lastEditedRef.current === "radius") {
      const newContour = thicknessMm / scaleMmPerM;
      if (
        Number.isFinite(newContour) &&
        Math.abs(newContour - contourInterval) > 0.01
      ) {
        isInternalUpdate.current = true;
        form.set("model.contour_interval_m", Number(newContour.toFixed(2)));
        setTimeout(() => {
          isInternalUpdate.current = false;
        }, 0);
      }
    } else {
      const newRadius =
        (contourInterval * widthMm) / (2 * thicknessMm);
      if (Number.isFinite(newRadius) && Math.abs(newRadius - radius) > 0.5) {
        isInternalUpdate.current = true;
        form.set("region.radius_m", Number(newRadius.toFixed(1)));
        setTimeout(() => {
          isInternalUpdate.current = false;
        }, 0);
      }
    }

    if (widthIn !== heightIn) {
      isInternalUpdate.current = true;
      form.set("model.height_inches", widthIn);
      setTimeout(() => {
        isInternalUpdate.current = false;
      }, 0);
    }
  }, [widthIn, heightIn, radius, thicknessMm, contourInterval, form]);

  const handleFinish = (e: FormEvent) => {
    e.preventDefault();
    const mergedProcessing = {
      ...DEFAULT_CONFIG.processing,
      ...config.processing,
      calibration: {
        ...DEFAULT_CONFIG.processing.calibration,
        ...(config.processing?.calibration || {}),
      },
      nesting: {
        ...DEFAULT_CONFIG.processing.nesting,
        ...(config.processing?.nesting || {}),
      },
    };
    const payload: PipelineConfig = {
      experiment: { ...DEFAULT_CONFIG.experiment, ...config.experiment },
      region: { ...DEFAULT_CONFIG.region, ...config.region },
      model: { ...DEFAULT_CONFIG.model, ...config.model },
      data: { ...DEFAULT_CONFIG.data, ...config.data },
      profiles: { ...DEFAULT_CONFIG.profiles, ...(config.profiles || {}) },
      processing: mergedProcessing,
      export: { ...DEFAULT_CONFIG.export, ...config.export },
    };
    submitJob.mutate(payload);
  };

  const currentRunningJob =
    jobHistory.length > 0 ? allJobs?.[jobHistory[0]] : null;
  const isRunning =
    submitJob.isPending ||
    (currentRunningJob &&
      (currentRunningJob.status === "running" ||
        currentRunningJob.status === "pending"));

  const authButtonLabel = authUser ? authUser.email : "Login";

  const setField = (path: string) => (value: unknown) => {
    if (isInternalUpdate.current) return;
    if (
      path === "region.radius_m" ||
      path === "model.width_inches" ||
      path === "model.layer_thickness_mm"
    ) {
      lastEditedRef.current = "radius";
    }
    if (path === "model.contour_interval_m") {
      lastEditedRef.current = "contour";
    }
    form.set(path, value);
  };

  const disabled = !!isRunning;

  return (
    <div className="flex h-screen flex-col bg-background text-foreground font-sans">
      {/* ===== Header ===== */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-primary px-5">
        <h1 className="text-lg font-bold tracking-tight text-primary-foreground font-serif">
          TopoCut Studio
        </h1>
        <div className="flex items-center gap-2">
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="text-primary-foreground hover:bg-primary-foreground/10"
              >
                <User className="mr-1.5 h-4 w-4" />
                <span className="hidden sm:inline">{authButtonLabel}</span>
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-72">
              {!authUser ? (
                <div className="flex flex-col gap-3">
                  <h4 className="font-medium text-sm">Account</h4>
                  <Input
                    placeholder="Email"
                    value={authEmail}
                    onChange={(e) => setAuthEmail(e.target.value)}
                  />
                  <Input
                    type="password"
                    placeholder="Password"
                    value={authPassword}
                    onChange={(e) => setAuthPassword(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") login.mutate();
                    }}
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={() => login.mutate()}
                      disabled={login.isPending}
                    >
                      {login.isPending && (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      )}
                      Login
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => signup.mutate()}
                      disabled={signup.isPending}
                    >
                      {signup.isPending && (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      )}
                      Sign Up
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground">
                    Signed in as {authUser.email}
                  </p>
                  <Button size="sm" variant="outline" onClick={handleLogout}>
                    Logout
                  </Button>
                </div>
              )}
              {authError && (
                <p className="mt-2 text-xs text-destructive">{authError}</p>
              )}
            </PopoverContent>
          </Popover>

          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="text-primary-foreground hover:bg-primary-foreground/10"
                aria-label="Settings"
              >
                <Settings className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56">
              <h4 className="mb-3 font-medium text-sm">Settings</h4>
              <div className="flex items-center justify-between">
                <Label htmlFor="dark-mode" className="text-sm">
                  Dark Mode
                </Label>
                <div className="flex items-center gap-2">
                  <Sun className="h-3.5 w-3.5 text-muted-foreground" />
                  <Switch
                    id="dark-mode"
                    checked={isDarkMode}
                    onCheckedChange={setIsDarkMode}
                  />
                  <Moon className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </header>

      {/* ===== Body ===== */}
      <div className="flex flex-1 overflow-hidden">
        {/* ===== Sidebar ===== */}
        <aside className="flex w-[400px] shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground">
          <form
            id="config-form"
            onSubmit={handleFinish}
            className="flex flex-1 flex-col overflow-hidden"
          >
            <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">
              {/* Region */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Region</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <FormField label="Search location" htmlFor="search-loc">
                    <div className="flex gap-2">
                      <Input
                        id="search-loc"
                        placeholder="Search a place or address"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            handleSearchLocation(searchQuery);
                          }
                        }}
                        disabled={disabled}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        disabled={disabled || searchLoading}
                        onClick={() => handleSearchLocation(searchQuery)}
                      >
                        {searchLoading ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Search className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                    {searchError && (
                      <p className="mt-1 text-xs text-destructive">
                        {searchError}
                      </p>
                    )}
                  </FormField>

                  <div className="grid grid-cols-3 gap-3">
                    <FormField label="Latitude" htmlFor="lat">
                      <NumberInput
                        id="lat"
                        value={lat}
                        onChange={(v) => setField("region.center_lat")(v)}
                        step={0.0001}
                        formatter={formatCoord}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Longitude" htmlFor="lon">
                      <NumberInput
                        id="lon"
                        value={lon}
                        onChange={(v) => setField("region.center_lon")(v)}
                        step={0.0001}
                        formatter={formatCoord}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Radius (m)" htmlFor="radius">
                      <NumberInput
                        id="radius"
                        value={radius}
                        onChange={(v) => setField("region.radius_m")(v)}
                        step={100}
                        disabled={disabled}
                      />
                    </FormField>
                  </div>
                </CardContent>
              </Card>

              {/* Physical Model */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Physical Model</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div className="flex gap-3">
                    <FormField label="Width (in)" htmlFor="width" className="flex-1">
                      <NumberInput
                        id="width"
                        value={widthIn}
                        onChange={(v) => setField("model.width_inches")(v)}
                        step={0.1}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Height (in)" htmlFor="height" className="flex-1">
                      <NumberInput
                        id="height"
                        value={heightIn}
                        onChange={() => {}}
                        step={0.1}
                        disabled
                      />
                    </FormField>
                  </div>
                  <FormField label="Layer Thickness" htmlFor="thickness">
                    <Select
                      value={String(thicknessMm)}
                      onValueChange={(v) =>
                        setField("model.layer_thickness_mm")(parseFloat(v))
                      }
                      disabled={disabled}
                    >
                      <SelectTrigger id="thickness">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="0.1016">
                          {'Paper 0.004" (0.1016 mm)'}
                        </SelectItem>
                        <SelectItem value="6.35">
                          {'1/4" (6.35 mm)'}
                        </SelectItem>
                        <SelectItem value="3.175">
                          {'1/8" (3.175 mm)'}
                        </SelectItem>
                        <SelectItem value="1.5875">
                          {'1/16" (1.5875 mm)'}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </FormField>
                  <FormField label="Contour Interval (m)" htmlFor="contour">
                    <NumberInput
                      id="contour"
                      value={contourInterval}
                      onChange={(v) => setField("model.contour_interval_m")(v)}
                      step={1}
                      disabled={disabled}
                    />
                  </FormField>
                  <p className="text-xs text-muted-foreground">
                    Width sets the model scale. Radius and contour interval
                    auto-adjust to match the selected layer thickness.
                  </p>
                </CardContent>
              </Card>

              {/* Data Sources */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Data Sources</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <FormField label="DEM Source" htmlFor="dem">
                    <Select
                      value={config.data.dem_source}
                      onValueChange={(v) => form.set("data.dem_source", v)}
                      disabled={disabled}
                    >
                      <SelectTrigger id="dem">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="glo_30">
                          Copernicus GLO-30 (Global)
                        </SelectItem>
                        <SelectItem value="3dep">
                          USGS 3DEP (USA Only)
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </FormField>
                  <FormField label="Imagery Source" htmlFor="imagery">
                    <Select
                      value={config.data.imagery_source}
                      onValueChange={(v) => form.set("data.imagery_source", v)}
                      disabled={disabled}
                    >
                      <SelectTrigger id="imagery">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="naip">NAIP (USA Only)</SelectItem>
                        <SelectItem value="sentinel-2-l2a">
                          Sentinel-2 (Global)
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </FormField>
                  <FormField label="Imagery Resolution" htmlFor="res">
                    <Select
                      value={config.data.imagery_resolution}
                      onValueChange={(v) =>
                        form.set("data.imagery_resolution", v)
                      }
                      disabled={disabled}
                    >
                      <SelectTrigger id="res">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1m">1m (Native - Slow)</SelectItem>
                        <SelectItem value="5m">5m (Preview)</SelectItem>
                        <SelectItem value="10m">10m (Fast)</SelectItem>
                      </SelectContent>
                    </Select>
                  </FormField>
                </CardContent>
              </Card>

              {/* Processing */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <CardTitle className="text-base">Processing</CardTitle>
                  <Switch
                    checked={config.processing.geometric_smoothing}
                    onCheckedChange={(v) =>
                      form.set("processing.geometric_smoothing", v)
                    }
                    disabled={disabled}
                    aria-label="Geometric smoothing"
                  />
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div>
                    <p className="text-sm font-medium">Smooth Borders</p>
                    <p className="text-xs text-muted-foreground">
                      Applies geometric smoothing to reduce jagged contour edges
                      for cleaner laser paths.
                    </p>
                  </div>
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">Normalize Texture</p>
                    <Switch
                      checked={config.processing.texture_normalize}
                      onCheckedChange={(v) =>
                        form.set("processing.texture_normalize", v)
                      }
                      disabled={disabled}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Equalizes contrast before dithering for more consistent
                    grayscale textures.
                  </p>
                  <FormField label="Normalize Cutoff (%)" htmlFor="cutoff">
                    <NumberInput
                      id="cutoff"
                      value={config.processing.texture_normalize_cutoff}
                      onChange={(v) =>
                        form.set("processing.texture_normalize_cutoff", v)
                      }
                      min={0}
                      max={10}
                      step={0.5}
                      disabled={disabled}
                    />
                  </FormField>
                  <FormField label="Texture Gamma" htmlFor="gamma">
                    <NumberInput
                      id="gamma"
                      value={config.processing.texture_gamma}
                      onChange={(v) => form.set("processing.texture_gamma", v)}
                      min={0.5}
                      max={2.0}
                      step={0.05}
                      disabled={disabled}
                    />
                  </FormField>
                </CardContent>
              </Card>

              {/* Profiles */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Profiles</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <FormField label="Machine Profile" htmlFor="machine">
                    <Select
                      value={selectedMachineProfileId}
                      onValueChange={handleMachineProfileSelect}
                      disabled={disabled}
                    >
                      <SelectTrigger id="machine">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {builtInMachineProfiles.map((p) => (
                          <SelectItem key={p.id} value={p.id}>
                            {p.name}
                          </SelectItem>
                        ))}
                        {customMachineProfiles.length > 0 && (
                          <>
                            {customMachineProfiles.map((p) => (
                              <SelectItem key={p.id} value={p.id}>
                                {p.name} (Saved)
                              </SelectItem>
                            ))}
                          </>
                        )}
                      </SelectContent>
                    </Select>
                  </FormField>
                  <div className="flex gap-2">
                    <Input
                      placeholder="Profile name (optional)"
                      value={machineProfileNameInput}
                      onChange={(e) =>
                        setMachineProfileNameInput(e.target.value)
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          saveMachineProfile();
                        }
                      }}
                      disabled={!authUser}
                      className="flex-1"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => saveMachineProfile()}
                      disabled={!authUser || isCustomProfilesLoading}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => deleteSelectedCustomMachineProfile()}
                      disabled={!authUser || !selectedMachineIsCustom}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>

                  <FormField label="Material Profile" htmlFor="material">
                    <Select
                      value={selectedMaterialProfileId}
                      onValueChange={handleMaterialProfileSelect}
                      disabled={disabled}
                    >
                      <SelectTrigger id="material">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {builtInMaterialProfiles.map((p) => (
                          <SelectItem key={p.id} value={p.id}>
                            {p.name}
                          </SelectItem>
                        ))}
                        {customMaterialProfiles.length > 0 && (
                          <>
                            {customMaterialProfiles.map((p) => (
                              <SelectItem key={p.id} value={p.id}>
                                {p.name} (Saved)
                              </SelectItem>
                            ))}
                          </>
                        )}
                      </SelectContent>
                    </Select>
                  </FormField>
                  <div className="flex gap-2">
                    <Input
                      placeholder="Profile name (optional)"
                      value={materialProfileNameInput}
                      onChange={(e) =>
                        setMaterialProfileNameInput(e.target.value)
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          saveMaterialProfile();
                        }
                      }}
                      disabled={!authUser}
                      className="flex-1"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => saveMaterialProfile()}
                      disabled={!authUser || isCustomProfilesLoading}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => deleteSelectedCustomMaterialProfile()}
                      disabled={!authUser || !selectedMaterialIsCustom}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Nesting */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <CardTitle className="text-base">Nesting</CardTitle>
                  <Switch
                    checked={config.processing.nesting.enabled}
                    onCheckedChange={(v) =>
                      form.set("processing.nesting.enabled", v)
                    }
                    disabled={disabled}
                    aria-label="Enable nesting"
                  />
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <p className="text-xs text-muted-foreground">
                    Packs layers onto sheet layouts for efficient cutting and
                    composite previews.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <FormField label="Bed Width (in)" htmlFor="bedW">
                      <NumberInput
                        id="bedW"
                        value={bedWidthIn}
                        onChange={(v) =>
                          form.set("processing.nesting.bed_width_in", v)
                        }
                        step={1}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Bed Height (in)" htmlFor="bedH">
                      <NumberInput
                        id="bedH"
                        value={bedHeightIn}
                        onChange={(v) =>
                          form.set("processing.nesting.bed_height_in", v)
                        }
                        step={1}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Sheet Width (in)" htmlFor="sheetW">
                      <NumberInput
                        id="sheetW"
                        value={sheetWidthIn}
                        onChange={(v) =>
                          form.set("processing.nesting.sheet_width_in", v)
                        }
                        step={1}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Sheet Height (in)" htmlFor="sheetH">
                      <NumberInput
                        id="sheetH"
                        value={sheetHeightIn}
                        onChange={(v) =>
                          form.set("processing.nesting.sheet_height_in", v)
                        }
                        step={1}
                        disabled={disabled}
                      />
                    </FormField>
                  </div>
                  <FormField label="Sheet Margin (in)" htmlFor="margin">
                    <NumberInput
                      id="margin"
                      value={sheetMarginIn}
                      onChange={(v) =>
                        form.set("processing.nesting.sheet_margin_in", v)
                      }
                      step={0.0625}
                      disabled={disabled}
                    />
                  </FormField>
                  <FormField label="Part Gap (in)" htmlFor="gap">
                    <NumberInput
                      id="gap"
                      value={sheetGapIn}
                      onChange={(v) =>
                        form.set("processing.nesting.sheet_gap_in", v)
                      }
                      step={0.03125}
                      disabled={disabled}
                    />
                  </FormField>
                </CardContent>
              </Card>

              {/* Calibration Strip */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">
                    Calibration Strip
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="flex items-center justify-between col-span-2">
                      <Label className="text-sm">Enable Calibration</Label>
                      <Switch
                        checked={calibrationEnabled}
                        onCheckedChange={(v) =>
                          form.set("processing.calibration.enabled", v)
                        }
                        disabled={disabled}
                      />
                    </div>
                    <FormField label="Gamma Steps" htmlFor="gSteps">
                      <NumberInput
                        id="gSteps"
                        value={config.processing.calibration.gamma_steps}
                        onChange={(v) =>
                          form.set("processing.calibration.gamma_steps", v)
                        }
                        min={2}
                        max={20}
                        step={1}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Gamma Min" htmlFor="gMin">
                      <NumberInput
                        id="gMin"
                        value={config.processing.calibration.gamma_min}
                        onChange={(v) =>
                          form.set("processing.calibration.gamma_min", v)
                        }
                        min={0.05}
                        max={5}
                        step={0.05}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Gamma Max" htmlFor="gMax">
                      <NumberInput
                        id="gMax"
                        value={config.processing.calibration.gamma_max}
                        onChange={(v) =>
                          form.set("processing.calibration.gamma_max", v)
                        }
                        min={0.05}
                        max={5}
                        step={0.05}
                        disabled={disabled}
                      />
                    </FormField>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <FormField label="Strip W (mm)" htmlFor="sW">
                      <NumberInput
                        id="sW"
                        value={config.processing.calibration.strip_width_mm}
                        onChange={(v) =>
                          form.set("processing.calibration.strip_width_mm", v)
                        }
                        min={40}
                        max={400}
                        step={1}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Strip H (mm)" htmlFor="sH">
                      <NumberInput
                        id="sH"
                        value={config.processing.calibration.strip_height_mm}
                        onChange={(v) =>
                          form.set("processing.calibration.strip_height_mm", v)
                        }
                        min={16}
                        max={120}
                        step={1}
                        disabled={disabled}
                      />
                    </FormField>
                    <FormField label="Pad (mm)" htmlFor="pad">
                      <NumberInput
                        id="pad"
                        value={config.processing.calibration.padding_mm}
                        onChange={(v) =>
                          form.set("processing.calibration.padding_mm", v)
                        }
                        min={0.5}
                        max={10}
                        step={0.5}
                        disabled={disabled}
                      />
                    </FormField>
                  </div>
                </CardContent>
              </Card>

              {/* Experiment */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Experiment</CardTitle>
                </CardHeader>
                <CardContent>
                  <FormField label="Name" htmlFor="exp-name">
                    <Input
                      id="exp-name"
                      value={config.experiment.name}
                      onChange={(e) =>
                        form.set("experiment.name", e.target.value)
                      }
                      disabled={disabled}
                      required
                    />
                  </FormField>
                </CardContent>
              </Card>

              {/* Alerts */}
              {submitJob.isError && (
                <Alert variant="destructive">
                  <AlertTitle>Submission Failed</AlertTitle>
                  <AlertDescription>
                    {submitJob.error.message}
                  </AlertDescription>
                </Alert>
              )}
              {allJobsError && (
                <Alert variant="warning">
                  <AlertTitle>Job status unavailable</AlertTitle>
                  <AlertDescription>
                    Unable to fetch job status from the backend. Results will
                    appear once the connection resumes.
                  </AlertDescription>
                </Alert>
              )}
            </div>

            {/* Pinned submit bar */}
            <div className="shrink-0 border-t border-border bg-background px-5 py-4 shadow-[0_-4px_12px_rgba(0,0,0,0.06)]">
              <Button
                type="submit"
                className="w-full"
                size="lg"
                disabled={!authUser || disabled}
              >
                {isRunning ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Processing...
                  </>
                ) : authUser ? (
                  "Generate Relief"
                ) : (
                  "Login to Generate"
                )}
              </Button>
              {!authUser && (
                <p className="mt-2 text-xs text-muted-foreground text-center">
                  Use the Login button at top-right to submit and view
                  account-specific jobs.
                </p>
              )}

              {isRunning && currentRunningJob && (
                <div className="mt-3 flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <Progress
                      value={currentRunningJob.progress}
                      className="flex-1"
                    />
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive"
                          aria-label="Cancel job"
                        >
                          <XCircle className="h-4 w-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Cancel this job?</AlertDialogTitle>
                          <AlertDialogDescription>
                            This will stop processing and no outputs will be
                            produced.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Keep running</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() =>
                              cancelJob.mutate(currentRunningJob.id)
                            }
                          >
                            Cancel
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {currentRunningJob.message}
                  </p>
                </div>
              )}
            </div>
          </form>
        </aside>

        {/* ===== Main Content ===== */}
        <main className="flex flex-1 flex-col overflow-hidden bg-card">
          <Tabs
            value={activeTab}
            onValueChange={setActiveTab}
            className="flex flex-1 flex-col"
          >
            <div className="flex items-center justify-between border-b border-border px-4 pt-2">
              <TabsList>
                <TabsTrigger value="map">Map Selector</TabsTrigger>
                <TabsTrigger value="jobs" className="flex items-center gap-1.5">
                  Job History
                  {jobHistory.length > 0 && (
                    <Badge
                      variant="secondary"
                      className="ml-1 h-5 min-w-5 px-1.5 text-xs"
                    >
                      {jobHistory.length}
                    </Badge>
                  )}
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="map" className="relative flex-1 mt-0">
              <div className="absolute inset-0">
                <MapSelector
                  lat={lat}
                  lon={lon}
                  radius={radius}
                  setCoords={handleMapCoords}
                  isActive={activeTab === "map"}
                />
              </div>
            </TabsContent>

            <TabsContent
              value="jobs"
              className="flex-1 overflow-y-auto p-4 mt-0"
            >
              {!authUser ? (
                <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
                  <User className="h-10 w-10 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    Login to view your jobs.
                  </p>
                </div>
              ) : jobHistory.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
                  <RefreshCw className="h-10 w-10 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    No jobs run yet. Configure settings and click Generate
                    Relief.
                  </p>
                </div>
              ) : (
                <Accordion
                  type="multiple"
                  value={expandedJobs}
                  onValueChange={setExpandedJobs}
                  className="flex flex-col gap-3"
                >
                  {jobHistory.map((jId, idx) => {
                    const job = allJobs?.[jId];
                    const displayJob: JobInfo =
                      job ??
                      ({
                        id: jId,
                        status: "pending",
                        progress: 0,
                        message: "Fetching status...",
                        result_path: undefined,
                        error: undefined,
                        created_at: "",
                        config_summary: "Fetching status...",
                      } as JobInfo);

                    return (
                      <AccordionItem
                        key={jId}
                        value={jId}
                        className="rounded-xl border border-border bg-card px-4 overflow-hidden"
                      >
                        <AccordionTrigger className="hover:no-underline py-3">
                          <div className="flex flex-1 items-center gap-3 pr-2">
                            {getStatusIcon(displayJob.status)}
                            <span className="font-medium text-sm">
                              Run #{jobHistory.length - idx}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {formatTime(displayJob.created_at)}
                            </span>
                            <span className="text-xs text-muted-foreground hidden md:inline">
                              {displayJob.config_summary}
                            </span>
                            <div className="ml-auto flex items-center gap-2">
                              {displayJob.status !== "running" &&
                                displayJob.status !== "pending" && (
                                  <AlertDialog>
                                    <AlertDialogTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-7 w-7"
                                        aria-label="Remove job"
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        <XCircle className="h-3.5 w-3.5" />
                                      </Button>
                                    </AlertDialogTrigger>
                                    <AlertDialogContent>
                                      <AlertDialogHeader>
                                        <AlertDialogTitle>
                                          Remove this job from history?
                                        </AlertDialogTitle>
                                      </AlertDialogHeader>
                                      <AlertDialogFooter>
                                        <AlertDialogCancel>
                                          Keep
                                        </AlertDialogCancel>
                                        <AlertDialogAction
                                          onClick={() =>
                                            handleDeleteJob(displayJob.id)
                                          }
                                        >
                                          Remove
                                        </AlertDialogAction>
                                      </AlertDialogFooter>
                                    </AlertDialogContent>
                                  </AlertDialog>
                                )}
                              {getStatusBadge(displayJob.status)}
                            </div>
                          </div>
                        </AccordionTrigger>
                        <AccordionContent>
                          {displayJob.status === "running" ||
                          displayJob.status === "pending" ? (
                            <div className="py-4 flex flex-col gap-3">
                              <div className="flex items-center gap-2">
                                <Progress
                                  value={displayJob.progress}
                                  className="flex-1"
                                />
                                <AlertDialog>
                                  <AlertDialogTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-8 w-8 text-destructive"
                                      aria-label="Cancel job"
                                    >
                                      <XCircle className="h-4 w-4" />
                                    </Button>
                                  </AlertDialogTrigger>
                                  <AlertDialogContent>
                                    <AlertDialogHeader>
                                      <AlertDialogTitle>
                                        Cancel this job?
                                      </AlertDialogTitle>
                                      <AlertDialogDescription>
                                        This will stop processing and no outputs
                                        will be produced.
                                      </AlertDialogDescription>
                                    </AlertDialogHeader>
                                    <AlertDialogFooter>
                                      <AlertDialogCancel>
                                        Keep running
                                      </AlertDialogCancel>
                                      <AlertDialogAction
                                        onClick={() =>
                                          cancelJob.mutate(displayJob.id)
                                        }
                                      >
                                        Cancel
                                      </AlertDialogAction>
                                    </AlertDialogFooter>
                                  </AlertDialogContent>
                                </AlertDialog>
                              </div>
                              <p className="text-xs text-muted-foreground">
                                {displayJob.message}
                              </p>
                            </div>
                          ) : displayJob.status === "failed" ? (
                            <Alert variant="destructive" className="my-2">
                              <AlertTitle>Job Failed</AlertTitle>
                              <AlertDescription>
                                {displayJob.error}
                              </AlertDescription>
                            </Alert>
                          ) : displayJob.status === "canceled" ? (
                            <Alert variant="info" className="my-2">
                              <AlertTitle>Job Canceled</AlertTitle>
                              <AlertDescription>
                                Canceled by user.
                              </AlertDescription>
                            </Alert>
                          ) : (
                            <JobResultsPanel
                              jobId={displayJob.id}
                              isCompleted={
                                displayJob.status === "completed"
                              }
                              authToken={authToken ?? undefined}
                            />
                          )}
                        </AccordionContent>
                      </AccordionItem>
                    );
                  })}
                </Accordion>
              )}
            </TabsContent>
          </Tabs>
        </main>
      </div>
    </div>
  );
}

export default App;

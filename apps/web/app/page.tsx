"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ContextSidebar } from "../components/context-sidebar";
import { ReportHistorySidebar } from "../components/report-history-sidebar";
import { ReportView } from "../components/report-view";
import { ResearchComposer } from "../components/research-composer";
import type {
  ApiHealthResponse,
  ChatJobEventsResponse,
  ChatJobRecord,
  ChatJobStreamPayload,
  ChatJobWebsocketNotification,
  ChatJobWebsocketResponse,
  ChatJobsResponse,
  ChatResponse,
  ChatSession,
  ComposerLibraryResponse,
  DirectorySelectionResponse,
  EvidenceResponse,
  HealthState,
  ReportHistoryResponse,
  RolloutDiagnostics
} from "../lib/chat-types";
import {
  chatResponseFromSession,
  chatSessionsFromJobs,
  chatSessionFromReport,
  copyText,
  isResumeIntent
} from "../lib/report-adapter";

const DEFAULT_API_URL = "http://127.0.0.1:8765";
const DEFAULT_LIBRARY_DIR = "/Users/a123/paper-copilot-test-pdfs";
const DEFAULT_PROMPT =
  "基于可见光-红外行人重识别（VI-ReID），先选一个性能强但仍有改进故事的强基线，再从本地 CCF A 论文里找 3 个可兼容模块，给出中文实验方案。";
const LIBRARY_DIR_STORAGE_KEY = "paper-copilot.libraryDir";
const ACTIVE_JOB_STORAGE_KEY = "paper-copilot.activeJobId";
const JOB_POLL_INTERVAL_MS = 1200;
const DIAGNOSTICS_POLL_INTERVAL_MS = 3000;

export default function Home() {
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [jobWebsocketUrl, setJobWebsocketUrl] = useState<string | null>(null);
  const [message, setMessage] = useState(DEFAULT_PROMPT);
  const [pdfDir, setPdfDir] = useState(DEFAULT_LIBRARY_DIR);
  const [health, setHealth] = useState<HealthState>("checking");
  const [isRunning, setIsRunning] = useState(false);
  const [isInterrupting, setIsInterrupting] = useState(false);
  const [isSelectingLibraryDir, setIsSelectingLibraryDir] = useState(false);
  const [isLoadingLibraryStatus, setIsLoadingLibraryStatus] = useState(false);
  const [libraryStatus, setLibraryStatus] = useState<ComposerLibraryResponse | null>(null);
  const [libraryStatusError, setLibraryStatusError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [legacySessions, setLegacySessions] = useState<ChatSession[]>([]);
  const [jobs, setJobs] = useState<ChatJobRecord[]>([]);
  const [activeJob, setActiveJob] = useState<ChatJobRecord | null>(null);
  const [jobEvents, setJobEvents] = useState<ChatJobEventsResponse["events"]>([]);
  const [diagnostics, setDiagnostics] = useState<RolloutDiagnostics | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [isLoadingDiagnostics, setIsLoadingDiagnostics] = useState(false);
  const diagnosticsRequestId = useRef(0);
  const jobEventCursor = useRef<{
    jobId: string | null;
    after: number;
    isLoading: boolean;
  }>({
    jobId: null,
    after: 0,
    isLoading: false
  });
  const jobWebsocket = useRef<WebSocket | null>(null);
  const jobWebsocketJobId = useRef<string | null>(null);
  const jobWebsocketRequestId = useRef(0);
  const pendingJobWebsocketRequests = useRef(
    new Map<
      number,
      {
        resolve: (record: ChatJobRecord) => void;
        reject: (error: Error) => void;
      }
    >()
  );
  const [isSidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isInspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceResponse | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [isLoadingEvidence, setIsLoadingEvidence] = useState(false);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);

  const normalizedApiUrl = useMemo(() => apiUrl.replace(/\/+$/, ""), [apiUrl]);
  const sessions = useMemo(() => {
    const jobSessions = chatSessionsFromJobs(jobs);
    const jobSessionPaths = new Set(
      jobs
        .map((job) => job.result?.session_path ?? null)
        .filter((path): path is string => path !== null)
    );
    return [
      ...jobSessions,
      ...legacySessions.filter(
        (session) =>
          session.run === null || !jobSessionPaths.has(session.run.session_path)
      )
    ];
  }, [jobs, legacySessions]);
  const activeSession = useMemo(
    () => sessions.find((session) => session.id === selectedReportId) ?? null,
    [selectedReportId, sessions]
  );
  const activeJobStatus = activeJob?.status ?? null;
  const jobProgress = jobEvents.at(-1)?.message ?? null;
  const canSubmit = health === "online" && !isRunning;
  const canStop =
    health === "online" &&
    activeJob !== null &&
    isActiveJobStatus(activeJob.status);

  async function checkHealth() {
    setHealth("checking");
    try {
      const response = await fetch(`${normalizedApiUrl}/health`, { method: "GET" });
      if (!response.ok) {
        setJobWebsocketUrl(null);
        setHealth("offline");
        return;
      }
      const payload = (await response.json()) as ApiHealthResponse;
      setJobWebsocketUrl(payload.websocket_url ?? null);
      setHealth("online");
    } catch {
      setJobWebsocketUrl(null);
      setHealth("offline");
    }
  }

  useEffect(() => {
    void checkHealth();
  }, [normalizedApiUrl]);

  useEffect(() => {
    if (health !== "offline") {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${normalizedApiUrl}/health`, { method: "GET" });
        if (response.ok) {
          const payload = (await response.json()) as ApiHealthResponse;
          setJobWebsocketUrl(payload.websocket_url ?? null);
          setHealth("online");
        }
      } catch {
        return;
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [health, normalizedApiUrl]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(LIBRARY_DIR_STORAGE_KEY);
      if (saved !== null) {
        setPdfDir(saved);
      }
    } catch {
      return;
    }
  }, []);

  useEffect(() => {
    void loadReports();
    void loadJobs(true);
  }, [normalizedApiUrl]);

  useEffect(() => {
    if (health === "online") {
      void loadJobs(true);
    }
  }, [health]);

  useEffect(() => {
    if (activeJob === null) {
      setIsInterrupting(false);
      return;
    }
    const isActive = isActiveJobStatus(activeJob.status);
    const isResumable = isResumableJobStatus(activeJob.status);
    if (!isActive) {
      setIsInterrupting(false);
    }
    if (!isActive && !isResumable) {
      return;
    }

    const jobId = activeJob.id;
    let disposed = false;
    let terminalReceived = false;
    let websocket: WebSocket | null = null;
    let eventSource: EventSource | null = null;
    let pollTimer: number | null = null;

    const currentAfter = () =>
      jobEventCursor.current.jobId === jobId ? jobEventCursor.current.after : 0;

    const startPolling = () => {
      if (disposed || terminalReceived || pollTimer !== null) {
        return;
      }
      void refreshActiveJob(jobId);
      pollTimer = window.setInterval(() => {
        void refreshActiveJob(jobId);
      }, JOB_POLL_INTERVAL_MS);
    };

    const startSse = () => {
      if (disposed || terminalReceived || eventSource !== null || pollTimer !== null) {
        return;
      }
      websocket?.close();
      websocket = null;
      const streamUrl = `${normalizedApiUrl}/jobs/${jobId}/stream?after=${currentAfter()}`;
      eventSource = new EventSource(streamUrl);
      eventSource.onmessage = (event) => {
        const payload = JSON.parse(event.data) as ChatJobStreamPayload;
        terminalReceived = !isActiveJobStatus(payload.record.status);
        applyJobStreamPayload(jobId, payload);
        if (terminalReceived) {
          eventSource?.close();
          eventSource = null;
        }
      };
      eventSource.onerror = () => {
        eventSource?.close();
        eventSource = null;
        startPolling();
      };
    };

    if (jobWebsocketUrl === null) {
      startSse();
    } else {
      try {
        const websocketBase = jobWebsocketUrl.replace(/\/+$/, "");
        const socket = new WebSocket(
          `${websocketBase}/jobs/${jobId}/stream?after=${currentAfter()}`
        );
        websocket = socket;
        socket.onopen = () => {
          jobWebsocket.current = socket;
          jobWebsocketJobId.current = jobId;
        };
        socket.onmessage = (event) => {
          const message = JSON.parse(String(event.data)) as
            | ChatJobWebsocketNotification
            | ChatJobWebsocketResponse;
          if ("method" in message && message.method === "job/events") {
            terminalReceived = !isActiveJobStatus(message.params.record.status);
            applyJobStreamPayload(jobId, message.params);
            return;
          }
          if (!("id" in message)) {
            return;
          }
          const pending = pendingJobWebsocketRequests.current.get(message.id);
          if (pending === undefined) {
            return;
          }
          pendingJobWebsocketRequests.current.delete(message.id);
          if (message.error !== undefined) {
            pending.reject(new Error(message.error.message));
          } else if (message.result !== undefined) {
            pending.resolve(message.result.record);
          }
        };
        socket.onerror = () => {
          startSse();
        };
        socket.onclose = () => {
          if (jobWebsocket.current === socket) {
            jobWebsocket.current = null;
            jobWebsocketJobId.current = null;
            rejectPendingJobWebsocketRequests("WebSocket 连接已关闭。");
          }
          startSse();
        };
      } catch {
        startSse();
      }
    }

    return () => {
      disposed = true;
      if (jobWebsocket.current === websocket) {
        jobWebsocket.current = null;
        jobWebsocketJobId.current = null;
        rejectPendingJobWebsocketRequests("WebSocket 连接已切换。");
      }
      websocket?.close();
      eventSource?.close();
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
      }
    };
  }, [activeJob?.id, activeJob?.status, normalizedApiUrl, jobWebsocketUrl]);

  useEffect(() => {
    if (activeJob === null || activeJob.attempts.length === 0) {
      diagnosticsRequestId.current += 1;
      setDiagnostics(null);
      setDiagnosticsError(null);
      setIsLoadingDiagnostics(false);
      return;
    }
    const jobId = activeJob.id;
    const attempt = activeJob.attempts.at(-1)?.number ?? null;
    setDiagnostics((current) =>
      current?.job_id === jobId && current.attempt === attempt ? current : null
    );
    setDiagnosticsError(null);
    void loadJobDiagnostics(jobId, true);
    if (!isActiveJobStatus(activeJob.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadJobDiagnostics(jobId, false);
    }, DIAGNOSTICS_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [activeJob?.id, activeJob?.status, activeJob?.attempts.length, normalizedApiUrl]);

  useEffect(() => {
    if (health !== "online" || pdfDir.trim().length === 0) {
      return;
    }
    void loadLibraryStatus();
  }, [health, normalizedApiUrl, pdfDir]);

  async function loadReports(): Promise<boolean> {
    try {
      const response = await fetch(`${normalizedApiUrl}/reports`, { method: "GET" });
      if (!response.ok) {
        return false;
      }
      const payload = (await response.json()) as ReportHistoryResponse;
      setLegacySessions(payload.reports.map(chatSessionFromReport));
      return true;
    } catch {
      return false;
    }
  }

  async function refreshReports() {
    const [reportsOk, jobsOk] = await Promise.all([loadReports(), loadJobs(false)]);
    const ok = reportsOk || jobsOk;
    showNotice(ok ? "历史已刷新" : "刷新失败");
  }

  async function loadJobs(restoreActive: boolean): Promise<boolean> {
    try {
      const response = await fetch(`${normalizedApiUrl}/jobs`, { method: "GET" });
      if (!response.ok) {
        return false;
      }
      const payload = (await response.json()) as ChatJobsResponse;
      setHealth("online");
      setJobs(payload.jobs);
      if (restoreActive) {
        const rememberedId = readActiveJobId();
        const restored = payload.jobs.find((job) => job.id === rememberedId);
        if (restored !== undefined) {
          activateJob(restored);
          void loadJobEvents(restored.id);
        }
      }
      return true;
    } catch {
      return false;
    }
  }

  async function refreshActiveJob(jobId: string): Promise<void> {
    try {
      const response = await fetch(`${normalizedApiUrl}/jobs/${jobId}`, {
        method: "GET"
      });
      if (!response.ok) {
        return;
      }
      const record = (await response.json()) as ChatJobRecord;
      setHealth("online");
      activateJob(record);
      await loadJobEvents(jobId);
      if (record.status === "completed") {
        void loadReports();
      }
    } catch {
      setHealth("offline");
    }
  }

  function applyJobStreamPayload(
    jobId: string,
    payload: ChatJobStreamPayload
  ): void {
    const isNewJob = jobEventCursor.current.jobId !== jobId;
    if (isNewJob) {
      jobEventCursor.current = { jobId, after: 0, isLoading: false };
      setJobEvents([]);
    }
    const after = jobEventCursor.current.after;
    const freshEvents = payload.events.filter((event) => event.seq > after);
    jobEventCursor.current.after = Math.max(after, payload.next_after);
    if (freshEvents.length > 0) {
      setJobEvents((events) => [...events, ...freshEvents]);
    }
    setHealth("online");
    activateJob(payload.record);
    if (payload.record.status === "completed") {
      void loadReports();
    }
  }

  function rejectPendingJobWebsocketRequests(message: string): void {
    for (const pending of pendingJobWebsocketRequests.current.values()) {
      pending.reject(new Error(message));
    }
    pendingJobWebsocketRequests.current.clear();
  }

  function requestJobWebsocketControl(
    method: "job/interrupt" | "job/resume",
    jobId: string
  ): Promise<ChatJobRecord | null> {
    const socket = jobWebsocket.current;
    if (
      socket === null ||
      socket.readyState !== WebSocket.OPEN ||
      jobWebsocketJobId.current !== jobId
    ) {
      return Promise.resolve(null);
    }
    jobWebsocketRequestId.current += 1;
    const requestId = jobWebsocketRequestId.current;
    return new Promise((resolve, reject) => {
      pendingJobWebsocketRequests.current.set(requestId, { resolve, reject });
      try {
        socket.send(
          JSON.stringify({
            id: requestId,
            method,
            params: {}
          })
        );
      } catch (exc) {
        pendingJobWebsocketRequests.current.delete(requestId);
        reject(exc instanceof Error ? exc : new Error("WebSocket 控制请求失败。"));
      }
    });
  }

  async function loadJobEvents(jobId: string): Promise<void> {
    const isNewJob = jobEventCursor.current.jobId !== jobId;
    if (isNewJob) {
      jobEventCursor.current = { jobId, after: 0, isLoading: false };
      setJobEvents([]);
    }
    if (jobEventCursor.current.isLoading) {
      return;
    }
    jobEventCursor.current.isLoading = true;
    try {
      const params = new URLSearchParams({
        after: String(jobEventCursor.current.after)
      });
      const response = await fetch(
        `${normalizedApiUrl}/jobs/${jobId}/events?${params.toString()}`,
        { method: "GET" }
      );
      if (!response.ok) {
        return;
      }
      const payload = (await response.json()) as ChatJobEventsResponse;
      if (jobEventCursor.current.jobId !== jobId) {
        return;
      }
      const after = jobEventCursor.current.after;
      const freshEvents = payload.events.filter((event) => event.seq > after);
      jobEventCursor.current.after = Math.max(after, payload.next_after);
      if (freshEvents.length > 0) {
        setJobEvents((events) => [...events, ...freshEvents]);
      }
    } catch {
      return;
    } finally {
      if (jobEventCursor.current.jobId === jobId) {
        jobEventCursor.current.isLoading = false;
      }
    }
  }

  async function loadJobDiagnostics(
    jobId: string,
    showLoading: boolean
  ): Promise<boolean> {
    diagnosticsRequestId.current += 1;
    const requestId = diagnosticsRequestId.current;
    if (showLoading) {
      setIsLoadingDiagnostics(true);
    }
    try {
      const response = await fetch(`${normalizedApiUrl}/jobs/${jobId}/diagnostics`, {
        method: "GET"
      });
      const raw = (await response.json()) as
        | RolloutDiagnostics
        | { error?: { message?: string } };
      if (requestId !== diagnosticsRequestId.current) {
        return false;
      }
      if (!response.ok) {
        throw new Error(apiErrorMessage(raw, "运行诊断读取失败。"));
      }
      setDiagnostics(raw as RolloutDiagnostics);
      setDiagnosticsError(null);
      return true;
    } catch (exc) {
      if (requestId !== diagnosticsRequestId.current) {
        return false;
      }
      setDiagnosticsError(exc instanceof Error ? exc.message : "运行诊断读取失败。");
      return false;
    } finally {
      if (requestId === diagnosticsRequestId.current) {
        setIsLoadingDiagnostics(false);
      }
    }
  }

  async function refreshJobDiagnostics(): Promise<void> {
    if (activeJob === null || activeJob.attempts.length === 0) {
      showNotice("Trace 尚未开始写入");
      return;
    }
    const ok = await loadJobDiagnostics(activeJob.id, true);
    showNotice(ok ? "运行诊断已刷新" : "运行诊断刷新失败");
  }

  async function loadLibraryStatus(): Promise<boolean> {
    const trimmedDir = pdfDir.trim();
    if (trimmedDir.length === 0) {
      setLibraryStatus(null);
      setLibraryStatusError(null);
      return false;
    }
    setIsLoadingLibraryStatus(true);
    setLibraryStatusError(null);
    try {
      const params = new URLSearchParams({ pdf_dir: trimmedDir });
      const response = await fetch(`${normalizedApiUrl}/composer/library?${params.toString()}`, {
        method: "GET"
      });
      const raw = (await response.json()) as
        | ComposerLibraryResponse
        | { error?: { message?: string } };
      setHealth("online");
      if (!response.ok) {
        const messageText =
          "error" in raw && raw.error?.message ? raw.error.message : "资料库检查失败。";
        throw new Error(messageText);
      }
      setLibraryStatus(raw as ComposerLibraryResponse);
      return true;
    } catch (exc) {
      setLibraryStatus(null);
      setLibraryStatusError(exc instanceof Error ? exc.message : "资料库检查失败。");
      return false;
    } finally {
      setIsLoadingLibraryStatus(false);
    }
  }

  async function refreshLibraryStatus() {
    const ok = await loadLibraryStatus();
    showNotice(ok ? "资料库状态已刷新" : "资料库状态刷新失败");
  }

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedMessage = message.trim();
    if (trimmedMessage.length === 0) {
      setError("请输入研究问题。");
      return;
    }
    if (health !== "online") {
      setError("本地 API 未连接，请先启动后端服务。");
      return;
    }

    setIsRunning(true);
    setError(null);
    try {
      const resumableJob =
        activeJob !== null && isResumableJobStatus(activeJob.status)
          ? activeJob
          : undefined;
      if (isResumeIntent(trimmedMessage)) {
        if (resumableJob === undefined) {
          setError("没有可恢复的中断任务。");
          setIsRunning(false);
          return;
        }
        await resumeJob(resumableJob);
        return;
      }

      await createJob(trimmedMessage);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "请求失败。");
      setIsRunning(false);
    }
  }

  async function createJob(request: string): Promise<void> {
    const payload = {
      message: request,
      conversation_id: activeJob?.spec.conversation_id ?? null,
      pdf_dir: pdfDir.trim().length > 0 ? pdfDir.trim() : null
    };
    let response: Response;
    try {
      response = await fetch(`${normalizedApiUrl}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } catch {
      setHealth("offline");
      throw new Error("无法连接本地 API。");
    }

    const raw = (await response.json()) as
      | ChatJobRecord
      | { error?: { message?: string } };
    setHealth("online");
    if (!response.ok) {
      throw new Error(apiErrorMessage(raw, "任务创建失败。"));
    }
    const record = raw as ChatJobRecord;
    activateJob(record);
    setMessage("");
    setSelectedEvidence(null);
    setEvidenceError(null);
    void loadJobEvents(record.id);
  }

  async function resumeJob(job: ChatJobRecord): Promise<void> {
    const websocketRecord = await requestJobWebsocketControl("job/resume", job.id);
    if (websocketRecord !== null) {
      activateJob(websocketRecord);
      setMessage("");
      setSelectedEvidence(null);
      setEvidenceError(null);
      void loadJobEvents(websocketRecord.id);
      return;
    }

    let response: Response;
    try {
      response = await fetch(`${normalizedApiUrl}/jobs/${job.id}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
    } catch {
      setHealth("offline");
      throw new Error("无法连接本地 API。");
    }

    const raw = (await response.json()) as
      | ChatJobRecord
      | { error?: { message?: string } };
    setHealth("online");
    if (!response.ok) {
      throw new Error(apiErrorMessage(raw, "任务恢复失败。"));
    }
    const record = raw as ChatJobRecord;
    activateJob(record);
    setMessage("");
    setSelectedEvidence(null);
    setEvidenceError(null);
    void loadJobEvents(record.id);
  }

  async function interruptActiveJob(): Promise<void> {
    if (activeJob === null || !isActiveJobStatus(activeJob.status)) {
      return;
    }
    setIsInterrupting(true);
    setError(null);
    try {
      const websocketRecord = await requestJobWebsocketControl(
        "job/interrupt",
        activeJob.id
      );
      if (websocketRecord !== null) {
        activateJob(websocketRecord);
        void loadJobEvents(websocketRecord.id);
        return;
      }
    } catch (exc) {
      setIsInterrupting(false);
      setError(exc instanceof Error ? exc.message : "停止任务失败。");
      return;
    }

    let response: Response;
    try {
      response = await fetch(`${normalizedApiUrl}/jobs/${activeJob.id}/interrupt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
    } catch {
      setHealth("offline");
      setIsInterrupting(false);
      setError("无法连接本地 API，不能停止当前任务。");
      return;
    }

    const raw = (await response.json()) as
      | ChatJobRecord
      | { error?: { message?: string } };
    setHealth("online");
    if (!response.ok) {
      setIsInterrupting(false);
      setError(apiErrorMessage(raw, "停止任务失败。"));
      return;
    }
    const record = raw as ChatJobRecord;
    activateJob(record);
    void loadJobEvents(record.id);
  }

  function activateJob(record: ChatJobRecord) {
    setActiveJob(record);
    setResult(record.result);
    setSelectedReportId(record.spec.conversation_id ?? record.id);
    setIsRunning(isActiveJobStatus(record.status));
    setJobs((items) => [record, ...items.filter((item) => item.id !== record.id)]);
    writeActiveJobId(record.id);
  }

  function createSession() {
    setError(null);
    setResult(null);
    setActiveJob(null);
    setJobEvents([]);
    jobEventCursor.current = { jobId: null, after: 0, isLoading: false };
    setIsRunning(false);
    setIsInterrupting(false);
    setMessage("");
    setSelectedReportId(null);
    setSelectedEvidence(null);
    setEvidenceError(null);
    writeActiveJobId(null);
  }

  function selectSession(session: ChatSession) {
    setError(null);
    setSelectedEvidence(null);
    setEvidenceError(null);
    setMessage("");
    setSelectedReportId(session.id);
    setResult(chatResponseFromSession(session));
    if (session.jobId !== null) {
      const job = jobs.find((item) => item.id === session.jobId);
      if (job !== undefined) {
        activateJob(job);
        void loadJobEvents(job.id);
      }
      return;
    }
    setActiveJob(null);
    setJobEvents([]);
    jobEventCursor.current = { jobId: null, after: 0, isLoading: false };
    setIsRunning(false);
    setIsInterrupting(false);
    writeActiveJobId(null);
  }

  function updateLibraryDir(value: string) {
    setPdfDir(value);
    try {
      const trimmed = value.trim();
      if (trimmed.length > 0) {
        window.localStorage.setItem(LIBRARY_DIR_STORAGE_KEY, value);
      } else {
        window.localStorage.removeItem(LIBRARY_DIR_STORAGE_KEY);
      }
    } catch {
      return;
    }
  }

  async function selectLibraryDir() {
    setIsSelectingLibraryDir(true);
    setError(null);
    try {
      let response: Response;
      try {
        response = await fetch(`${normalizedApiUrl}/library/select-directory`, {
          method: "POST"
        });
      } catch {
        setHealth("offline");
        throw new Error("无法连接本地 API，不能打开目录选择器。");
      }

      const raw = (await response.json()) as
        | DirectorySelectionResponse
        | { error?: { message?: string } };
      setHealth("online");
      if (!response.ok) {
        const messageText =
          "error" in raw && raw.error?.message ? raw.error.message : "目录选择失败。";
        throw new Error(messageText);
      }

      const selectedPath = (raw as DirectorySelectionResponse).path;
      if (selectedPath === null) {
        showNotice("未选择目录");
        return;
      }
      updateLibraryDir(selectedPath);
      showNotice("资料库已选择");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "目录选择失败。");
    } finally {
      setIsSelectingLibraryDir(false);
    }
  }

  async function copyWithNotice(value: string, label: string) {
    const ok = await copyText(value);
    showNotice(ok ? `${label}已复制` : "复制失败");
  }

  async function openEvidence(ref: string) {
    setIsLoadingEvidence(true);
    setEvidenceError(null);
    setSelectedEvidence(null);
    try {
      const params = new URLSearchParams({ ref });
      const response = await fetch(`${normalizedApiUrl}/evidence?${params.toString()}`, {
        method: "GET"
      });
      const raw = (await response.json()) as EvidenceResponse | { error?: { message?: string } };
      setHealth("online");
      if (!response.ok) {
        const messageText =
          "error" in raw && raw.error?.message ? raw.error.message : "证据反查失败。";
        throw new Error(messageText);
      }
      setSelectedEvidence(raw as EvidenceResponse);
      showNotice("证据已打开");
    } catch (exc) {
      setEvidenceError(exc instanceof Error ? exc.message : "证据反查失败。");
    } finally {
      setIsLoadingEvidence(false);
    }
  }

  function showNotice(text: string) {
    setCopyNotice(text);
    window.setTimeout(() => setCopyNotice(null), 1600);
  }

  return (
    <main className={`app-shell${isSidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <ReportHistorySidebar
        canCreate
        isCollapsed={isSidebarCollapsed}
        onCreate={createSession}
        onSelect={selectSession}
        sessions={sessions}
        selectedReportId={selectedReportId}
      />

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-leading">
            <button
              aria-label={isSidebarCollapsed ? "显示会话栏" : "隐藏会话栏"}
              className="toolbar-icon-button"
              onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
              title={isSidebarCollapsed ? "显示会话栏" : "隐藏会话栏"}
              type="button"
            >
              <span aria-hidden="true">☰</span>
            </button>
            <div className="workspace-title">
              <strong>Paper Copilot</strong>
              <span>研究</span>
            </div>
          </div>
          <div className="topbar-actions">
            <button className={`api-status ${health}`} onClick={checkHealth} type="button">
              <span aria-hidden="true" />
              {healthLabel(health)}
            </button>
            <button
              aria-label={isInspectorCollapsed ? "显示研究上下文" : "隐藏研究上下文"}
              className="toolbar-icon-button"
              onClick={() => setInspectorCollapsed((collapsed) => !collapsed)}
              title={isInspectorCollapsed ? "显示研究上下文" : "隐藏研究上下文"}
              type="button"
            >
              <span aria-hidden="true">▤</span>
            </button>
          </div>
        </header>

        <div className={`content-grid${isInspectorCollapsed ? " inspector-collapsed" : ""}`}>
          <section className="main-pane" aria-label="研究输入">
            {error ? <p className="error-strip">{error}</p> : null}

            <ReportView
              copyNotice={copyNotice}
              isRunning={isRunning}
              jobError={activeJob?.error ?? null}
              jobStatus={activeJobStatus}
              onCopy={copyWithNotice}
              onEvidenceRefClick={openEvidence}
              onRefresh={refreshReports}
              progress={jobProgress}
              messages={activeSession?.messages ?? []}
              result={result}
            />

            <ResearchComposer
              canStop={canStop}
              canSubmit={canSubmit}
              health={health}
              isInterrupting={isInterrupting}
              isRunning={isRunning}
              message={message}
              onMessageChange={setMessage}
              onStop={interruptActiveJob}
              onSubmit={submitRequest}
              showSuggestions={activeSession === null && !isRunning}
            />
          </section>

          <ContextSidebar
            apiUrl={apiUrl}
            diagnostics={diagnostics}
            diagnosticsError={diagnosticsError}
            evidenceError={evidenceError}
            isCollapsed={isInspectorCollapsed}
            isLoadingEvidence={isLoadingEvidence}
            isLoadingDiagnostics={isLoadingDiagnostics}
            isLoadingLibraryStatus={isLoadingLibraryStatus}
            isSelectingLibraryDir={isSelectingLibraryDir}
            jobId={activeJob?.id ?? null}
            jobProgress={jobProgress}
            jobStatus={activeJobStatus}
            libraryStatus={libraryStatus}
            libraryStatusError={libraryStatusError}
            onApiUrlChange={setApiUrl}
            onCopy={copyWithNotice}
            onEvidenceRefClick={openEvidence}
            onLibraryDirChange={updateLibraryDir}
            onRefreshLibraryStatus={refreshLibraryStatus}
            onRefreshDiagnostics={refreshJobDiagnostics}
            onSelectLibraryDir={selectLibraryDir}
            pdfDir={pdfDir}
            result={result}
            selectedEvidence={selectedEvidence}
          />
        </div>
      </section>
    </main>
  );
}

function healthLabel(health: HealthState): string {
  switch (health) {
    case "online":
      return "API 已连接";
    case "offline":
      return "API 离线";
    case "checking":
      return "正在检查 API";
  }
}

function isActiveJobStatus(status: ChatJobRecord["status"]): boolean {
  return status === "queued" || status === "running";
}

function isResumableJobStatus(status: ChatJobRecord["status"]): boolean {
  return status === "interrupted" || status === "failed";
}

function apiErrorMessage(
  payload: unknown,
  fallback: string
): string {
  if (typeof payload !== "object" || payload === null || !("error" in payload)) {
    return fallback;
  }
  const error = payload.error;
  if (typeof error !== "object" || error === null || !("message" in error)) {
    return fallback;
  }
  return typeof error.message === "string" ? error.message : fallback;
}

function readActiveJobId(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeActiveJobId(jobId: string | null): void {
  try {
    if (jobId === null) {
      window.localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
    } else {
      window.localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, jobId);
    }
  } catch {
    return;
  }
}

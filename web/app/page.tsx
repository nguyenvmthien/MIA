"use client"

import { useSession, signIn, signOut } from "next-auth/react"
import { useState, useCallback, useEffect, useRef } from "react"
import {
  Upload, Users, CheckCircle2, Circle, Calendar,
  LogOut, Loader2, ChevronDown, ChevronUp, AlertCircle, Mic,
  Sparkles, ArrowRight, UserPlus, X, History, UserCheck,
} from "lucide-react"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const ACTIVE_MEETING_KEY = "mia.activeMeetingId"

// ── Types ─────────────────────────────────────────────────────────────────────

type Worker = { worker_id: string; name: string; role?: string; email?: string; aliases?: string[] }
type Task = {
  task_id: string; description: string; assignee?: string; assignee_id?: string
  due_date?: string; priority?: string; extraction_confidence?: number
  selected?: boolean; edited_description?: string; edited_assignee?: string; edited_due_date?: string
}
type ParticipantDetail = { speaker_id: string; display_name: string; worker_id: string | null }
type MeetingResult = {
  meeting_id: string; status?: string; job_status?: string
  summary_text?: string; participants?: string[]
  participants_detail?: ParticipantDetail[]
  action_items: Task[]; human_review_items: Task[]; unresolved_items: Task[]
  run_metrics?: { total_tokens_used: number; tasks_extracted: number; stage_timings: Record<string, number> }
}

type Step = "upload" | "processing" | "review" | "done"

// ── Step indicator ─────────────────────────────────────────────────────────────

function StepBar({ current }: { current: Step }) {
  const steps: { id: Step; label: string }[] = [
    { id: "upload", label: "Upload" },
    { id: "processing", label: "Processing" },
    { id: "review", label: "Review" },
    { id: "done", label: "Done" },
  ]
  const idx = steps.findIndex(s => s.id === current)

  return (
    <div className="flex items-center justify-between mb-10 px-1">
      {steps.map((s, i) => (
        <div key={s.id} className="flex items-center flex-1">
          <div className="flex flex-col items-center gap-1.5">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold transition-all duration-300
              ${i < idx
                ? "bg-sky-600 text-white shadow-lg shadow-sky-900/20"
                : i === idx
                ? "bg-sky-500 text-white ring-4 ring-sky-500/15 shadow-lg shadow-sky-900/20"
                : "bg-white text-slate-500 border border-slate-200"}`}>
              {i < idx ? <CheckCircle2 size={14} strokeWidth={2.5} /> : i + 1}
            </div>
            <span className={`text-[11px] font-medium whitespace-nowrap transition-colors
              ${i <= idx ? "text-slate-800" : "text-slate-500"}`}>
              {s.label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div className={`flex-1 h-px mx-2 mb-4 transition-colors duration-300
              ${i < idx ? "bg-sky-600" : "bg-slate-200"}`} />
          )}
        </div>
      ))}
    </div>
  )
}

// ── Upload step ────────────────────────────────────────────────────────────────

function UploadStep({ onSubmit }: { onSubmit: (file: File, roster: Worker[]) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [workers, setWorkers] = useState<Worker[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [rosterOpen, setRosterOpen] = useState(false)
  const [rosterQuery, setRosterQuery] = useState("")
  const [addOpen, setAddOpen] = useState(false)
  const [newName, setNewName] = useState("")
  const [newRole, setNewRole] = useState("")
  const [newEmail, setNewEmail] = useState("")
  const fileRef = useRef<HTMLInputElement>(null)
  const rosterRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API}/workers`).then(r => r.json()).then(d => setWorkers(d.workers ?? [])).catch(() => null)
  }, [])

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (rosterRef.current && !rosterRef.current.contains(event.target as Node)) {
        setRosterOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setRosterOpen(false)
      }
    }

    document.addEventListener("pointerdown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [])

  const addWorker = async () => {
    if (!newName.trim()) return
    const payload = { worker_id: "", name: newName.trim(), role: newRole || null, email: newEmail || null, aliases: [], skills: [] }
    const r = await fetch(`${API}/workers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
    if (r.ok) {
      const w = await r.json()
      setWorkers(prev => [...prev, w])
      setSelected(prev => [...prev, w.worker_id])
      setNewName(""); setNewRole(""); setNewEmail(""); setAddOpen(false)
    }
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) setFile(f)
  }, [])

  const noneSelected = selected.length === 0
  // If no explicit selection, submit with all workers (default = everyone)
  const rosterToSubmit = noneSelected ? workers : workers.filter(w => selected.includes(w.worker_id))
  const rosterMatches = workers.filter(worker => {
    const query = rosterQuery.trim().toLowerCase()
    if (!query) return true
    return [worker.name, worker.role ?? "", worker.email ?? "", ...(worker.aliases ?? [])]
      .some(value => value.toLowerCase().includes(query))
  })
  const selectedWorkers = workers.filter(worker => selected.includes(worker.worker_id))
  const rosterSummary = noneSelected
    ? `All ${workers.length} participants included`
    : selectedWorkers.length <= 2
      ? selectedWorkers.map(worker => worker.name).join(", ")
      : `${selectedWorkers.slice(0, 2).map(worker => worker.name).join(", ")} +${selectedWorkers.length - 2} more`
  const canSubmit = !!file

  return (
    <div className="space-y-6">
      {/* Drop zone */}
      <div
        onClick={() => fileRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 group
          ${dragging
            ? "border-sky-400 bg-sky-50 scale-[1.01]"
            : file
            ? "border-emerald-400/60 bg-emerald-50 hover:border-emerald-400/80"
            : "border-slate-200 hover:border-sky-300 hover:bg-sky-50/60"}`}
      >
        <input ref={fileRef} type="file" accept=".mp3,.wav,.m4a,.ogg,.mp4,.webm" className="hidden"
          onChange={e => e.target.files?.[0] && setFile(e.target.files[0])} />

        {file ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center">
              <CheckCircle2 size={24} className="text-emerald-600" />
            </div>
            <div>
              <p className="font-semibold text-slate-900 text-sm">{file.name}</p>
              <p className="text-xs text-slate-500 mt-0.5">{(file.size / 1024 / 1024).toFixed(1)} MB · click to change</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-sky-100 flex items-center justify-center group-hover:bg-sky-200 transition-colors">
              <Upload size={20} className="text-sky-600 group-hover:text-sky-700 transition-colors" />
            </div>
            <div>
              <p className="font-medium text-slate-900 text-sm">Drop audio file here</p>
              <p className="text-xs text-slate-500 mt-0.5">MP3 · WAV · M4A · OGG · MP4 · WebM</p>
            </div>
          </div>
        )}
      </div>

      {/* Participants */}
      <div className="space-y-3" ref={rosterRef}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Users size={14} className="text-sky-600 flex-shrink-0" />
            <h3 className="text-sm font-medium text-slate-900">Participants</h3>
          </div>
          <span className="text-[11px] text-slate-600 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-full flex-shrink-0">
            {noneSelected ? `all ${workers.length} included` : `${selected.length} chosen`}
          </span>
        </div>

        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setRosterOpen(prev => !prev)}
            className={`w-full min-h-12 flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-all ${
              rosterOpen
                ? "border-sky-500 bg-sky-50 ring-1 ring-sky-500/20"
                : "border-slate-200 bg-white hover:border-sky-300 hover:bg-sky-50/60"
            }`}
          >
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-slate-500">Choose participants</p>
              <p className={`mt-1 text-sm truncate ${noneSelected ? "text-slate-800" : "text-slate-900"}`}>
                {rosterSummary || "Select people for this meeting"}
              </p>
            </div>
            <ChevronDown size={16} className={`text-slate-500 transition-transform ${rosterOpen ? "rotate-180" : ""}`} />
          </button>

          {rosterOpen && (
            <div className="rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-sky-900/10 overflow-hidden">
              <div className="p-3 border-b border-slate-200 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-slate-500">Search roster</p>
                  <div className="flex items-center gap-2 text-[11px] flex-shrink-0">
                    <button
                      onClick={() => setSelected(workers.map(w => w.worker_id))}
                      className="px-2 py-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors"
                    >
                      Select all
                    </button>
                    <button
                      onClick={() => setSelected([])}
                      className="px-2 py-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors"
                    >
                      Use all
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 focus-within:border-sky-500 focus-within:ring-1 focus-within:ring-sky-500/20 transition-all">
                  <ChevronDown size={14} className="text-slate-400 rotate-90" />
                  <input
                    value={rosterQuery}
                    onChange={e => setRosterQuery(e.target.value)}
                    placeholder="Search by name, role, email, alias..."
                    className="w-full bg-transparent text-sm text-slate-900 placeholder-slate-400 outline-none"
                  />
                  {rosterQuery && (
                    <button
                      onClick={() => setRosterQuery("")}
                      className="text-slate-500 hover:text-slate-900 transition-colors"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              </div>

              <div className="max-h-72 overflow-y-auto p-2">
                {rosterMatches.length === 0 ? (
                  <div className="py-8 text-center text-sm text-slate-500">
                    No participants match your search.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {rosterMatches.map(worker => {
                      const isSelected = selected.includes(worker.worker_id)
                      return (
                        <button
                          key={worker.worker_id}
                          type="button"
                          onClick={() => setSelected(prev => (
                            prev.includes(worker.worker_id)
                              ? prev.filter(id => id !== worker.worker_id)
                              : [...prev, worker.worker_id]
                          ))}
                          className={`w-full flex items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors ${
                            isSelected
                              ? "bg-sky-50 hover:bg-sky-100"
                              : "hover:bg-slate-50"
                          }`}
                        >
                          <span className={`mt-0.5 flex h-5 w-5 items-center justify-center rounded-md border ${
                            isSelected ? "border-sky-500 bg-sky-500 text-white" : "border-slate-300 bg-white"
                          }`}>
                            {isSelected ? <CheckCircle2 size={12} /> : <Circle size={11} className="text-slate-400" />}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="text-sm font-medium text-slate-900 truncate">{worker.name}</span>
                              {worker.role && <span className="text-[11px] text-slate-500 truncate">{worker.role}</span>}
                            </div>
                            <div className="mt-0.5 text-[11px] text-slate-500 truncate">
                              {[worker.email, ...(worker.aliases ?? [])].filter(Boolean).join(" · ") || "No extra info"}
                            </div>
                          </div>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>

              <div className="border-t border-slate-200 p-3 flex items-center justify-between gap-3">
                <p className="text-[11px] text-slate-500">
                  Leaving this empty means everyone in the roster is included.
                </p>
                <button
                  type="button"
                  onClick={() => setRosterOpen(false)}
                  className="px-3 py-1.5 rounded-md bg-slate-100 hover:bg-slate-200 text-[11px] text-slate-700 transition-colors"
                >
                  Done
                </button>
              </div>
            </div>
          )}

          {selected.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-1">
              {selected.slice(0, 6).map(id => {
                const w = workers.find(worker => worker.worker_id === id)
                return w ? (
                  <span key={id} className="inline-flex items-center gap-1.5 bg-sky-50 border border-sky-200 text-sky-700 text-xs px-2.5 py-1 rounded-full">
                    <span className="max-w-28 truncate">{w.name}</span>
                    <button
                      type="button"
                      onClick={() => setSelected(prev => prev.filter(s => s !== id))}
                      className="hover:text-sky-900 transition-colors"
                    >
                      <X size={12} />
                    </button>
                  </span>
                ) : null
              })}
              {selected.length > 6 && <span className="text-xs text-slate-500 px-2 py-1">+{selected.length - 6} more</span>}
            </div>
          )}
        </div>

        <button
          onClick={() => setAddOpen(!addOpen)}
          className={`w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-xs font-medium border transition-all duration-150
            ${addOpen ? "border-sky-500 text-sky-600 bg-sky-50" : "border-dashed border-slate-300 text-slate-600 hover:border-sky-400 hover:text-slate-700 hover:bg-sky-50/60"}`}
        >
          <UserPlus size={13} />
          Add new participant
        </button>

        {addOpen && (
          <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-3 shadow-xl shadow-sky-900/10">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-500">New participant</span>
              <button onClick={() => setAddOpen(false)} className="text-slate-500 hover:text-slate-900 transition-colors">
                <X size={14} />
              </button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { val: newName, set: setNewName, ph: "Full name *", cols: "col-span-1" },
                { val: newRole, set: setNewRole, ph: "Role", cols: "" },
                { val: newEmail, set: setNewEmail, ph: "Email", cols: "" },
              ].map(({ val, set, ph, cols }) => (
                <input key={ph} value={val} onChange={e => set(e.target.value)} placeholder={ph}
                  className={`${cols} bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-xs text-slate-900 placeholder-slate-400
                    focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/20 transition-all`} />
              ))}
            </div>
            <button onClick={addWorker} disabled={!newName.trim()}
              className="px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg text-xs font-semibold text-white transition-colors shadow-sm shadow-sky-900/10">
              Save participant
            </button>
          </div>
        )}
      </div>

      <div className="space-y-2 pt-1">
        <button
          disabled={!canSubmit}
          onClick={() => file && onSubmit(file, rosterToSubmit)}
          className="w-full py-3 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl text-sm font-semibold text-white transition-all duration-150 flex items-center justify-center gap-2 shadow-lg shadow-sky-900/10"
        >
          <Sparkles size={15} />
          Analyse Meeting
          <ArrowRight size={15} />
        </button>
        {!canSubmit && (
          <p className="text-center text-xs text-slate-600">Select an audio file to continue</p>
        )}
      </div>
    </div>
  )
}

// ── Processing step ────────────────────────────────────────────────────────────

function ProcessingStep({ meetingId, onDone }: { meetingId: string; onDone: (r: MeetingResult) => void }) {
  const [status, setStatus] = useState("pending")
  const [error, setError] = useState("")

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`${API}/meetings/${meetingId}`)
        const data = await r.json()
        const s = data.status ?? data.job_status ?? "pending"
        setStatus(s)
        if (s === "completed") { clearInterval(interval); onDone(data) }
        if (s === "failed") { clearInterval(interval); setError(data.error ?? "Unknown error") }
      } catch {
        setError("Cannot reach backend")
        clearInterval(interval)
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [meetingId, onDone])

  const stages = [
    { id: "pending", label: "Queued", desc: "Waiting for worker" },
    { id: "processing", label: "Transcribing", desc: "Extracting tasks from audio" },
    { id: "completed", label: "Complete", desc: "Ready for review" },
  ]
  const currentIdx = stages.findIndex(s => s.id === status)

  return (
    <div className="flex flex-col items-center gap-10 py-10">
      {error ? (
        <div className="flex items-center gap-3 text-red-400 bg-red-950/30 border border-red-800/60 rounded-xl px-5 py-4 text-sm">
          <AlertCircle size={18} className="flex-shrink-0" />
          <span>{error}</span>
        </div>
      ) : (
        <>
          <div className="relative">
            <div className="w-16 h-16 rounded-full bg-sky-50 flex items-center justify-center">
              <Loader2 size={28} className="animate-spin text-sky-500" />
            </div>
            <div className="absolute inset-0 rounded-full animate-ping bg-sky-500/5" />
          </div>

          <div className="w-full max-w-xs space-y-4">
            {stages.map((s, i) => (
              <div key={s.id} className={`flex items-center gap-4 transition-all duration-300
                ${i < currentIdx ? "opacity-100" : i === currentIdx ? "opacity-100" : "opacity-30"}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-all
                  ${i < currentIdx
                    ? "bg-emerald-600"
                    : i === currentIdx
                    ? "bg-sky-600"
                    : "bg-white border border-slate-200"}`}>
                  {i < currentIdx
                    ? <CheckCircle2 size={14} className="text-white" />
                    : i === currentIdx
                    ? <Loader2 size={14} className="text-white animate-spin" />
                    : <Circle size={12} className="text-slate-400" />}
                </div>
                <div>
                  <p className={`text-sm font-medium ${i === currentIdx ? "text-slate-900" : i < currentIdx ? "text-slate-700" : "text-slate-500"}`}>
                    {s.label}
                  </p>
                  <p className="text-xs text-slate-500">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <p className="text-xs text-slate-500 font-mono">{meetingId}</p>
        </>
      )}
    </div>
  )
}

// ── Review step ────────────────────────────────────────────────────────────────

// ── Speaker resolver (inline in review) ───────────────────────────────────────

function InlineSpeakerResolver({
  meetingId,
  participants,
  workers,
  onResolved,
}: {
  meetingId: string
  participants: ParticipantDetail[]
  workers: Worker[]
  onResolved: () => void
}) {
  const unresolved = participants.filter(p => !p.worker_id)
  const [selections, setSelections] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)

  if (unresolved.length === 0) return null

  const resolve = async (speakerId: string) => {
    const workerId = selections[speakerId]
    const worker = workers.find(w => w.worker_id === workerId)
    if (!worker) return
    setSaving(speakerId)
    try {
      await fetch(`${API}/meetings/${meetingId}/participants/${encodeURIComponent(speakerId)}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ worker_id: workerId, display_name: worker.name }),
      })
      onResolved()
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2 text-amber-700 text-xs font-semibold">
        <UserCheck size={14} />
        {unresolved.length} speaker{unresolved.length > 1 ? "s" : ""} not matched — assign to roster
      </div>
      {unresolved.map(p => (
        <div key={p.speaker_id} className="flex items-center gap-2">
          <span className="text-xs text-slate-700 font-mono bg-slate-100 border border-slate-200 px-2 py-1 rounded-md w-28 truncate">
            {p.display_name}
          </span>
          <span className="text-slate-400 text-xs">→</span>
          <select
            value={selections[p.speaker_id] ?? ""}
            onChange={e => setSelections(prev => ({ ...prev, [p.speaker_id]: e.target.value }))}
            className="flex-1 bg-white border border-slate-200 rounded-lg px-2 py-1.5 text-xs text-slate-900 focus:outline-none focus:border-sky-500"
          >
            <option value="">Select worker...</option>
            {workers.map(w => (
              <option key={w.worker_id} value={w.worker_id}>
                {w.name}{w.role ? ` (${w.role})` : ""}
              </option>
            ))}
          </select>
          <button
            onClick={() => resolve(p.speaker_id)}
            disabled={!selections[p.speaker_id] || saving === p.speaker_id}
            className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 rounded-lg text-xs font-medium text-white transition-colors flex items-center gap-1 flex-shrink-0"
          >
            {saving === p.speaker_id ? <Loader2 size={11} className="animate-spin" /> : <UserCheck size={11} />}
            Assign
          </button>
        </div>
      ))}
    </div>
  )
}

function ReviewStep({
  result,
  onConfirm,
  onSkip,
}: {
  result: MeetingResult
  onConfirm: (allTasks: Task[]) => void
  onSkip: (allTasks: Task[]) => void
}) {
  // Unresolved speakers: their tasks start deselected until assigned
  const unresolvedLabels = new Set(
    (result.participants_detail ?? [])
      .filter(p => !p.worker_id)
      .flatMap(p => [p.speaker_id, p.display_name])
  )
  const [tasks, setTasks] = useState<Task[]>(
    result.action_items.map(t => ({
      ...t,
      selected: !t.assignee || !unresolvedLabels.has(t.assignee),
      edited_description: t.description,
      edited_assignee: t.assignee ?? "",
      edited_due_date: t.due_date ?? ""
    }))
  )
  const [summaryOpen, setSummaryOpen] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [workers, setWorkers] = useState<Worker[]>([])
  const [participants, setParticipants] = useState<ParticipantDetail[]>(result.participants_detail ?? [])

  useEffect(() => {
    fetch(`${API}/workers`).then(r => r.json()).then(d => setWorkers(d.workers ?? [])).catch(() => null)
  }, [])

  const refreshParticipants = async () => {
    try {
      const r = await fetch(`${API}/meetings/${result.meeting_id}`)
      const data = await r.json()
      setParticipants(data.participants_detail ?? [])
      // Sync updated assignees from backend; auto-select tasks that just got resolved
      if (data.action_items) {
        const nowResolvedLabels = new Set(
          ((data.participants_detail ?? []) as ParticipantDetail[])
            .filter(p => p.worker_id)
            .flatMap(p => [p.speaker_id, p.display_name])
        )
        setTasks(prev => prev.map(t => {
          const fresh = (data.action_items as Task[]).find(f => f.task_id === t.task_id)
          if (!fresh) return t
          const userEdited = t.edited_assignee !== (t.assignee ?? "")
          const justResolved = fresh.assignee && nowResolvedLabels.has(fresh.assignee)
          return {
            ...t,
            assignee: fresh.assignee,
            assignee_id: fresh.assignee_id,
            edited_assignee: userEdited ? t.edited_assignee : (fresh.assignee ?? ""),
            // Auto-select if this task's speaker just got resolved (and user hadn't manually deselected)
            selected: justResolved ? true : t.selected,
          }
        }))
      }
    } catch { /* non-fatal */ }
  }

  const toggle = (id: string) => setTasks(prev => prev.map(t => t.task_id === id ? { ...t, selected: !t.selected } : t))
  const update = (id: string, field: string, val: string) =>
    setTasks(prev => prev.map(t => t.task_id === id ? { ...t, [field]: val } : t))

  const selectedCount = tasks.filter(t => t.selected).length

  const handleConfirm = async () => {
    setSyncing(true)
    onConfirm(tasks)  // pass ALL tasks — parent extracts selected vs. deselected for feedback
  }

  const priorityStyles: Record<string, string> = {
    high: "bg-red-500/10 text-red-400 border-red-500/20",
    medium: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    low: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  }

  const confidenceColor = (c: number) =>
    c >= 0.8 ? "text-emerald-400" : c >= 0.6 ? "text-amber-400" : "text-red-400"

  return (
    <div className="space-y-5">
      {/* Speaker resolution */}
      {participants.some(p => !p.worker_id) && (
        <InlineSpeakerResolver
          meetingId={result.meeting_id}
          participants={participants}
          workers={workers}
          onResolved={refreshParticipants}
        />
      )}

      {/* Summary */}
      {result.summary_text && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm shadow-sky-900/5">
          <button onClick={() => setSummaryOpen(!summaryOpen)}
            className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wider hover:bg-slate-50 transition-colors">
            <span>Meeting Summary</span>
            {summaryOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {summaryOpen && (
            <div className="px-4 pb-4 text-sm text-slate-700 leading-relaxed border-t border-slate-200 pt-3">
              {result.summary_text}
            </div>
          )}
        </div>
      )}

      {/* Task list */}
      <div className="space-y-2">
        <div className="flex items-center justify-between py-1">
          <h3 className="text-sm font-semibold text-slate-900">
            Action Items
            <span className="ml-2 text-xs font-normal text-slate-500">{tasks.length} total</span>
          </h3>
          {selectedCount > 0 && (
            <span className="text-xs text-sky-700 bg-sky-50 border border-sky-200 px-2 py-0.5 rounded-full font-medium">
              {selectedCount} for Calendar
            </span>
          )}
        </div>

        {tasks.length === 0 ? (
          <div className="text-center py-12 text-slate-600">
            <Circle size={32} className="mx-auto mb-3 opacity-40" />
            <p className="text-sm">No action items extracted.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map(task => (
              <div key={task.task_id}
                className={`rounded-xl p-4 border transition-all duration-150 cursor-default
                  ${task.selected
                    ? "border-sky-300 bg-sky-50 shadow-sm shadow-sky-900/5"
                    : "border-slate-200 bg-white opacity-60"}`}>
                <div className="flex items-start gap-3">
                  <button onClick={() => toggle(task.task_id)} className="mt-0.5 flex-shrink-0 transition-transform hover:scale-110">
                    {task.selected
                      ? <CheckCircle2 size={18} className="text-sky-600" />
                      : <Circle size={18} className="text-slate-400" />}
                  </button>
                  <div className="flex-1 space-y-2.5">
                    <input
                      value={task.edited_description ?? ""}
                      onChange={e => update(task.task_id, "edited_description", e.target.value)}
                      className="w-full bg-transparent text-sm text-slate-900 font-medium focus:outline-none hover:bg-slate-50 focus:bg-slate-50 rounded-md px-1.5 py-0.5 -ml-1.5 transition-colors"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-md px-2 py-1">
                        <span className="text-slate-500 text-[11px]">👤</span>
                        <input value={task.edited_assignee ?? ""} onChange={e => update(task.task_id, "edited_assignee", e.target.value)}
                          placeholder="Assignee"
                          className="bg-transparent text-xs text-slate-600 focus:outline-none focus:text-slate-900 w-20 transition-colors" />
                      </div>
                      <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-md px-2 py-1">
                        <span className="text-slate-500 text-[11px]">📅</span>
                        <input type="date" value={task.edited_due_date ?? ""} onChange={e => update(task.task_id, "edited_due_date", e.target.value)}
                          className="bg-transparent text-xs text-slate-600 focus:outline-none focus:text-slate-900 transition-colors" />
                      </div>
                      {task.priority && (
                        <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${priorityStyles[task.priority] ?? "bg-slate-100 text-slate-700 border-slate-200"}`}>
                          {task.priority}
                        </span>
                      )}
                      {task.extraction_confidence !== undefined && (
                        <span className={`text-[11px] ${confidenceColor(task.extraction_confidence)}`}>
                          {Math.round(task.extraction_confidence * 100)}% confidence
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <button onClick={() => onSkip(tasks)}
          className="flex-1 py-3 border border-slate-200 hover:border-sky-300 rounded-xl text-sm text-slate-700 hover:text-slate-900 transition-all bg-white">
          Skip sync
        </button>
        <button
          onClick={handleConfirm}
          disabled={selectedCount === 0 || syncing}
          className="flex-[2] py-3 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl font-semibold text-sm transition-all shadow-lg shadow-sky-900/10 text-white flex items-center justify-center gap-2"
        >
          {syncing ? <Loader2 size={15} className="animate-spin" /> : <Calendar size={15} />}
          Create {selectedCount} Calendar Event{selectedCount !== 1 ? "s" : ""}
        </button>
      </div>
    </div>
  )
}

// ── Done step ──────────────────────────────────────────────────────────────────

function DoneStep({ events, onReset }: { events: { task_description: string; html_link?: string; due_date?: string }[]; onReset: () => void }) {
  return (
    <div className="flex flex-col items-center gap-6 py-8 text-center">
      <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center ring-8 ring-emerald-50">
        <CheckCircle2 size={32} className="text-emerald-600" />
      </div>
      <div>
        <h3 className="text-xl font-semibold text-slate-900">All done!</h3>
        <p className="text-sm text-slate-600 mt-1">
          {events.length} calendar event{events.length !== 1 ? "s" : ""} created successfully.
        </p>
      </div>

      {events.length > 0 && (
        <div className="w-full space-y-2 text-left">
          {events.map((ev, i) => (
            <div key={i} className="flex items-center justify-between bg-white border border-slate-200 rounded-xl px-4 py-3 shadow-sm">
              <span className="text-sm text-slate-900 truncate">{ev.task_description}</span>
              <div className="flex items-center gap-3 flex-shrink-0 ml-3">
                {ev.due_date && <span className="text-xs text-slate-500">{ev.due_date}</span>}
                {ev.html_link && (
                  <a href={ev.html_link} target="_blank" rel="noopener noreferrer"
                    className="text-xs text-sky-700 hover:text-sky-900 font-medium transition-colors">
                    Open ↗
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <button onClick={onReset}
        className="px-6 py-2.5 border border-slate-200 hover:border-sky-300 hover:bg-sky-50 rounded-xl text-sm text-slate-700 hover:text-slate-900 transition-all bg-white">
        Process another meeting
      </button>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Home() {
  const { data: session, status } = useSession()
  const [step, setStep] = useState<Step>("upload")
  const [meetingId, setMeetingId] = useState("")
  const [result, setResult] = useState<MeetingResult | null>(null)
  const [events, setEvents] = useState<{ task_description: string; html_link?: string; due_date?: string }[]>([])
  const [submitError, setSubmitError] = useState("")
  const [resumeLoading, setResumeLoading] = useState(false)

  const resumeMeeting = useCallback(async (id: string, persist = true) => {
    const trimmed = id.trim()
    if (!trimmed) return

    setResumeLoading(true)
    setSubmitError("")
    setMeetingId(trimmed)

    try {
      const r = await fetch(`${API}/meetings/${trimmed}`)
      const data = await r.json()
      const nextStatus = data.status ?? data.job_status ?? "pending"

      if (!r.ok || nextStatus === "failed") {
        localStorage.removeItem(ACTIVE_MEETING_KEY)
        setStep("upload")
        setSubmitError(data.error ?? data.detail ?? "Meeting processing failed")
        return
      }

      if (persist) localStorage.setItem(ACTIVE_MEETING_KEY, trimmed)

      if (nextStatus === "completed") {
        setResult(data)
        setStep("review")
      } else {
        setResult(null)
        setStep("processing")
      }
    } catch {
      setStep("upload")
      setSubmitError("Cannot resume meeting because the backend is unreachable")
    } finally {
      setResumeLoading(false)
    }
  }, [])

  useEffect(() => {
    if (status !== "authenticated") return
    const params = new URLSearchParams(window.location.search)
    const idFromUrl = params.get("meeting_id")
    const idFromStorage = localStorage.getItem(ACTIVE_MEETING_KEY)
    const idToResume = idFromUrl || idFromStorage
    if (idToResume) {
      const timer = window.setTimeout(() => {
        void resumeMeeting(idToResume)
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [status, resumeMeeting])

  const handleSubmit = async (file: File, roster: Worker[]) => {
    setSubmitError("")
    const form = new FormData()
    form.append("audio", file)
    form.append("roster_json", JSON.stringify({ workers: roster }))
    try {
      const r = await fetch(`${API}/meetings`, { method: "POST", body: form })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setMeetingId(data.meeting_id)
      localStorage.setItem(ACTIVE_MEETING_KEY, data.meeting_id)
      setStep("processing")
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Submission failed")
    }
  }

  const handleConfirm = async (allTasks: Task[]) => {
    // ── 1. Build implicit feedback from user edits ─────────────────────────
    const corrections: object[] = []

    for (const t of allTasks) {
      const descChanged = t.edited_description !== undefined && t.edited_description !== t.description
      const assigneeChanged = t.edited_assignee !== undefined && t.edited_assignee !== (t.assignee ?? "")
      const dateChanged = t.edited_due_date !== undefined && t.edited_due_date !== (t.due_date ?? "")

      if (!t.selected) {
        // User deselected the task → treat as false positive
        corrections.push({
          meeting_id: meetingId,
          task_id: t.task_id,
          original_description: t.description,
          original_assignee: t.assignee ?? null,
          original_due_date: t.due_date ?? null,
          is_false_positive: true,
        })
      } else if (descChanged || assigneeChanged || dateChanged) {
        // User edited fields → correction record
        corrections.push({
          meeting_id: meetingId,
          task_id: t.task_id,
          original_description: t.description,
          corrected_description: descChanged ? t.edited_description : null,
          original_assignee: t.assignee ?? null,
          corrected_assignee: assigneeChanged ? (t.edited_assignee || null) : null,
          original_due_date: t.due_date ?? null,
          corrected_due_date: dateChanged ? (t.edited_due_date || null) : null,
          is_false_positive: false,
        })
      }
    }

    // Fire-and-forget — feedback is best-effort and must not block the UX
    if (corrections.length > 0) {
      fetch(`${API}/meetings/${meetingId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ corrections, reviewer: session?.user?.email ?? null }),
      }).catch(() => null)
    }

    // ── 2. Sync selected tasks to Google Calendar ──────────────────────────
    const selectedTasks = allTasks.filter(t => t.selected)
    if (selectedTasks.length > 0 && session?.user?.email) {
      try {
        const r = await fetch("/api/calendar-sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ meetingId, taskIds: selectedTasks.map(t => t.task_id) }),
        })
        const data = await r.json()
        setEvents(data.events ?? [])
      } catch {
        setEvents([])
      }
    }

    localStorage.removeItem(ACTIVE_MEETING_KEY)
    setStep("done")
  }

  const handleSkip = async (allTasks: Task[]) => {
    // Submit feedback for any edits even when skipping calendar sync
    const corrections: object[] = []
    for (const t of allTasks) {
      const descChanged = t.edited_description !== undefined && t.edited_description !== t.description
      const assigneeChanged = t.edited_assignee !== undefined && t.edited_assignee !== (t.assignee ?? "")
      const dateChanged = t.edited_due_date !== undefined && t.edited_due_date !== (t.due_date ?? "")

      if (!t.selected) {
        corrections.push({
          meeting_id: meetingId,
          task_id: t.task_id,
          original_description: t.description,
          original_assignee: t.assignee ?? null,
          original_due_date: t.due_date ?? null,
          is_false_positive: true,
        })
      } else if (descChanged || assigneeChanged || dateChanged) {
        corrections.push({
          meeting_id: meetingId,
          task_id: t.task_id,
          original_description: t.description,
          corrected_description: descChanged ? t.edited_description : null,
          original_assignee: t.assignee ?? null,
          corrected_assignee: assigneeChanged ? (t.edited_assignee || null) : null,
          original_due_date: t.due_date ?? null,
          corrected_due_date: dateChanged ? (t.edited_due_date || null) : null,
          is_false_positive: false,
        })
      }
    }

    if (corrections.length > 0) {
      await fetch(`${API}/meetings/${meetingId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ corrections, reviewer: session?.user?.email ?? null }),
      }).catch(() => null)
    }

    localStorage.removeItem(ACTIVE_MEETING_KEY)
    setStep("done")
  }

  const reset = () => {
    localStorage.removeItem(ACTIVE_MEETING_KEY)
    setStep("upload"); setMeetingId(""); setResult(null); setEvents([])
  }

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 size={28} className="animate-spin text-sky-500" />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-8">
          {/* Brand */}
          <div className="text-center space-y-4">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-sky-50 border border-sky-200 mb-2">
              <Mic size={24} className="text-sky-600" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Meeting AI Agent</h1>
              <p className="text-sm text-slate-600 mt-2 leading-relaxed">
                Upload a meeting recording and get structured action items, automatically synced to Google Calendar.
              </p>
            </div>
          </div>

          {/* Features */}
          <div className="grid grid-cols-3 gap-3 text-center">
            {[
              { icon: "🎙️", label: "Transcribe" },
              { icon: "✅", label: "Extract tasks" },
              { icon: "📅", label: "Sync calendar" },
            ].map(f => (
              <div key={f.label} className="bg-white border border-slate-200 rounded-xl p-3 shadow-sm">
                <div className="text-lg mb-1">{f.icon}</div>
                <p className="text-[11px] text-slate-600 font-medium">{f.label}</p>
              </div>
            ))}
          </div>

          {/* Sign in */}
          <button
            onClick={() => signIn("google")}
            className="w-full flex items-center justify-center gap-3 px-5 py-3 bg-white hover:bg-slate-100 text-slate-900 rounded-xl font-semibold text-sm transition-all shadow-lg"
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      {/* Header */}
      <header className="border-b border-slate-200 px-6 py-3.5 flex items-center justify-between backdrop-blur-sm sticky top-0 bg-white/90 z-10">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center">
            <Mic size={13} className="text-sky-600" />
          </div>
          <span className="font-semibold text-sm text-slate-900">Meeting AI Agent</span>
        </div>
        <div className="flex items-center gap-3">
          <a href="/history"
            className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 transition-colors px-2 py-1 rounded-lg hover:bg-slate-100">
            <History size={13} />
            History
          </a>
          <a href="/roster"
            className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 transition-colors px-2 py-1 rounded-lg hover:bg-slate-100">
            <Users size={13} />
            Roster
          </a>
          {session.user?.image && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={session.user.image} alt="" className="w-7 h-7 rounded-full ring-2 ring-slate-200" />
          )}
          <span className="text-xs text-slate-500 hidden sm:block">{session.user?.email}</span>
          <button onClick={() => signOut()}
            className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 transition-colors px-2 py-1 rounded-lg hover:bg-slate-100">
            <LogOut size={13} />
            Sign out
          </button>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 flex justify-center px-4 py-10">
        <div className="w-full max-w-lg">
          <StepBar current={step} />

          {resumeLoading && (
            <div className="mb-5 flex items-center gap-3 text-sky-700 text-sm bg-sky-50 border border-sky-200 rounded-xl px-4 py-3">
              <Loader2 size={15} className="animate-spin flex-shrink-0" />
              Restoring your meeting...
            </div>
          )}

          {submitError && (
            <div className="mb-5 flex items-center gap-3 text-red-600 text-sm bg-red-50 border border-red-200 rounded-xl px-4 py-3">
              <AlertCircle size={15} className="flex-shrink-0" />
              {submitError}
            </div>
          )}

          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-2xl shadow-sky-900/5">
            {step === "upload" && <UploadStep onSubmit={handleSubmit} />}
            {step === "processing" && meetingId && (
              <ProcessingStep meetingId={meetingId} onDone={r => { setResult(r); setStep("review") }} />
            )}
            {step === "review" && result && (
              <ReviewStep result={result} onConfirm={handleConfirm} onSkip={handleSkip} />
            )}
            {step === "done" && <DoneStep events={events} onReset={reset} />}
          </div>
        </div>
      </main>
    </div>
  )
}

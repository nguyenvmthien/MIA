"use client"

import { useSession, signIn, signOut } from "next-auth/react"
import { useState, useCallback, useEffect, useRef } from "react"
import {
  Upload, Users, CheckCircle2, Circle, Calendar,
  LogOut, Loader2, ChevronDown, ChevronUp, AlertCircle, Mic
} from "lucide-react"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

// ── Types ─────────────────────────────────────────────────────────────────────

type Worker = { worker_id: string; name: string; role?: string; email?: string; aliases?: string[] }
type Task = {
  task_id: string; description: string; assignee?: string
  due_date?: string; priority?: string; extraction_confidence?: number
  selected?: boolean; edited_description?: string; edited_assignee?: string; edited_due_date?: string
}
type MeetingResult = {
  meeting_id: string; summary_text?: string; participants?: string[]
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
    <div className="flex items-center gap-0 mb-10">
      {steps.map((s, i) => (
        <div key={s.id} className="flex items-center">
          <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm font-medium transition-all
            ${i < idx ? "text-emerald-400" : i === idx ? "text-white" : "text-gray-500"}`}>
            {i < idx
              ? <CheckCircle2 size={16} className="text-emerald-400" />
              : <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center text-[10px] font-bold
                  ${i === idx ? "border-indigo-400 text-indigo-400" : "border-gray-600"}`}>
                  {i + 1}
                </div>
            }
            {s.label}
          </div>
          {i < steps.length - 1 && (
            <div className={`w-8 h-px ${i < idx ? "bg-emerald-700" : "bg-gray-700"}`} />
          )}
        </div>
      ))}
    </div>
  )
}

// ── Upload step ────────────────────────────────────────────────────────────────

function UploadStep({
  onSubmit,
}: {
  onSubmit: (file: File, roster: Worker[]) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [workers, setWorkers] = useState<Worker[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [addOpen, setAddOpen] = useState(false)
  const [newName, setNewName] = useState("")
  const [newRole, setNewRole] = useState("")
  const [newEmail, setNewEmail] = useState("")
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetch(`${API}/workers`).then(r => r.json()).then(d => setWorkers(d.workers ?? [])).catch(() => null)
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

  const selectedWorkers = workers.filter(w => selected.includes(w.worker_id))

  return (
    <div className="space-y-8">
      {/* Drop zone */}
      <div
        onClick={() => fileRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all
          ${dragging ? "border-indigo-400 bg-indigo-950/30" : "border-gray-700 hover:border-gray-500 hover:bg-gray-900/50"}
          ${file ? "border-emerald-600 bg-emerald-950/20" : ""}`}
      >
        <input ref={fileRef} type="file" accept=".mp3,.wav,.m4a,.ogg,.mp4,.webm" className="hidden"
          onChange={e => e.target.files?.[0] && setFile(e.target.files[0])} />
        {file ? (
          <div className="flex flex-col items-center gap-2">
            <CheckCircle2 size={36} className="text-emerald-400" />
            <p className="font-medium text-emerald-300">{file.name}</p>
            <p className="text-sm text-gray-500">{(file.size / 1024 / 1024).toFixed(1)} MB — click to change</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <Upload size={36} className="text-gray-500" />
            <p className="font-medium text-gray-300">Drop audio file here</p>
            <p className="text-sm text-gray-500">MP3, WAV, M4A, OGG, MP4, WebM</p>
          </div>
        )}
      </div>

      {/* Participants */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Users size={16} className="text-gray-400" />
          <h3 className="font-medium text-gray-200">Participants</h3>
        </div>
        <div className="flex flex-wrap gap-2 mb-3">
          {workers.map(w => (
            <button key={w.worker_id}
              onClick={() => setSelected(prev => prev.includes(w.worker_id) ? prev.filter(id => id !== w.worker_id) : [...prev, w.worker_id])}
              className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-all
                ${selected.includes(w.worker_id)
                  ? "bg-indigo-600 border-indigo-500 text-white"
                  : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"}`}>
              {w.name}{w.role ? ` · ${w.role}` : ""}
            </button>
          ))}
          <button onClick={() => setAddOpen(!addOpen)}
            className="px-3 py-1.5 rounded-full text-sm border border-dashed border-gray-600 text-gray-400 hover:border-gray-400 transition-all">
            + Add
          </button>
        </div>

        {addOpen && (
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Full name *"
                className="col-span-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-indigo-500" />
              <input value={newRole} onChange={e => setNewRole(e.target.value)} placeholder="Role"
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-indigo-500" />
              <input value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="Email"
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-indigo-500" />
            </div>
            <button onClick={addWorker} disabled={!newName.trim()}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 rounded-lg text-sm font-medium transition-colors">
              Save participant
            </button>
          </div>
        )}
      </div>

      <button
        disabled={!file || selected.length === 0}
        onClick={() => file && onSubmit(file, selectedWorkers)}
        className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl font-semibold transition-colors"
      >
        Submit Meeting
      </button>
      {!file && <p className="text-center text-xs text-gray-500">Select a file and at least one participant</p>}
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
    { id: "pending", label: "Queued" },
    { id: "processing", label: "Transcribing + extracting tasks" },
    { id: "completed", label: "Done" },
  ]
  const currentIdx = stages.findIndex(s => s.id === status)

  return (
    <div className="flex flex-col items-center gap-8 py-12">
      {error ? (
        <div className="flex items-center gap-3 text-red-400">
          <AlertCircle size={24} />
          <span>{error}</span>
        </div>
      ) : (
        <>
          <Loader2 size={48} className="animate-spin text-indigo-400" />
          <div className="space-y-3 w-full max-w-sm">
            {stages.map((s, i) => (
              <div key={s.id} className={`flex items-center gap-3 text-sm transition-all
                ${i < currentIdx ? "text-emerald-400" : i === currentIdx ? "text-white" : "text-gray-600"}`}>
                {i < currentIdx
                  ? <CheckCircle2 size={16} />
                  : i === currentIdx
                  ? <Loader2 size={16} className="animate-spin" />
                  : <Circle size={16} />}
                {s.label}
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500">Meeting ID: {meetingId}</p>
        </>
      )}
    </div>
  )
}

// ── Review step ────────────────────────────────────────────────────────────────

function ReviewStep({
  result,
  onConfirm,
  onSkip,
}: {
  result: MeetingResult
  onConfirm: (tasks: Task[]) => void
  onSkip: () => void
}) {
  const [tasks, setTasks] = useState<Task[]>(
    result.action_items.map(t => ({ ...t, selected: true, edited_description: t.description, edited_assignee: t.assignee ?? "", edited_due_date: t.due_date ?? "" }))
  )
  const [summaryOpen, setSummaryOpen] = useState(true)
  const [syncing, setSyncing] = useState(false)

  const toggle = (id: string) => setTasks(prev => prev.map(t => t.task_id === id ? { ...t, selected: !t.selected } : t))
  const update = (id: string, field: string, val: string) =>
    setTasks(prev => prev.map(t => t.task_id === id ? { ...t, [field]: val } : t))

  const selectedCount = tasks.filter(t => t.selected).length

  const handleConfirm = async () => {
    setSyncing(true)
    onConfirm(tasks.filter(t => t.selected))
  }

  const priorityColor: Record<string, string> = { high: "text-red-400", medium: "text-yellow-400", low: "text-green-400" }

  return (
    <div className="space-y-6">
      {/* Summary */}
      {result.summary_text && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <button onClick={() => setSummaryOpen(!summaryOpen)}
            className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-gray-300 hover:bg-gray-800/50 transition-colors">
            Meeting Summary
            {summaryOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
          {summaryOpen && (
            <div className="px-4 pb-4 text-sm text-gray-400 leading-relaxed border-t border-gray-800 pt-3">
              {result.summary_text}
            </div>
          )}
        </div>
      )}

      {/* Task list */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium text-gray-200">Action Items ({tasks.length})</h3>
          <span className="text-xs text-gray-500">{selectedCount} selected for Calendar</span>
        </div>

        {tasks.length === 0 && (
          <p className="text-center text-gray-500 py-8">No action items extracted.</p>
        )}

        <div className="space-y-3">
          {tasks.map(task => (
            <div key={task.task_id}
              className={`border rounded-xl p-4 transition-all ${task.selected ? "border-indigo-600/60 bg-indigo-950/20" : "border-gray-700 bg-gray-900/50 opacity-60"}`}>
              <div className="flex items-start gap-3">
                <button onClick={() => toggle(task.task_id)} className="mt-0.5 flex-shrink-0">
                  {task.selected
                    ? <CheckCircle2 size={20} className="text-indigo-400" />
                    : <Circle size={20} className="text-gray-600" />}
                </button>
                <div className="flex-1 space-y-2">
                  <input
                    value={task.edited_description ?? ""}
                    onChange={e => update(task.task_id, "edited_description", e.target.value)}
                    className="w-full bg-transparent text-sm text-gray-100 font-medium focus:outline-none focus:bg-gray-800 rounded px-1 -ml-1"
                  />
                  <div className="flex flex-wrap gap-3">
                    <div className="flex items-center gap-1 text-xs text-gray-400">
                      <span>👤</span>
                      <input value={task.edited_assignee ?? ""} onChange={e => update(task.task_id, "edited_assignee", e.target.value)}
                        placeholder="Assignee"
                        className="bg-transparent focus:outline-none focus:bg-gray-800 rounded px-1 w-24" />
                    </div>
                    <div className="flex items-center gap-1 text-xs text-gray-400">
                      <span>📅</span>
                      <input type="date" value={task.edited_due_date ?? ""} onChange={e => update(task.task_id, "edited_due_date", e.target.value)}
                        className="bg-transparent focus:outline-none focus:bg-gray-800 rounded px-1" />
                    </div>
                    {task.priority && (
                      <span className={`text-xs font-medium ${priorityColor[task.priority] ?? "text-gray-400"}`}>
                        {task.priority}
                      </span>
                    )}
                    {task.extraction_confidence !== undefined && (
                      <span className="text-xs text-gray-500">{Math.round(task.extraction_confidence * 100)}% confidence</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <button onClick={onSkip} className="flex-1 py-3 border border-gray-700 hover:border-gray-500 rounded-xl text-sm text-gray-400 transition-colors">
          Skip Calendar sync
        </button>
        <button
          onClick={handleConfirm}
          disabled={selectedCount === 0 || syncing}
          className="flex-1 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl font-semibold text-sm transition-colors flex items-center justify-center gap-2"
        >
          {syncing ? <Loader2 size={16} className="animate-spin" /> : <Calendar size={16} />}
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
      <CheckCircle2 size={56} className="text-emerald-400" />
      <div>
        <h3 className="text-xl font-semibold text-gray-100">All done!</h3>
        <p className="text-gray-400 mt-1">{events.length} Calendar event{events.length !== 1 ? "s" : ""} created.</p>
      </div>
      {events.length > 0 && (
        <div className="w-full space-y-2 text-left">
          {events.map((ev, i) => (
            <div key={i} className="flex items-center justify-between bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 text-sm">
              <span className="text-gray-300 truncate">{ev.task_description}</span>
              <div className="flex items-center gap-3 flex-shrink-0 ml-3">
                {ev.due_date && <span className="text-gray-500">{ev.due_date}</span>}
                {ev.html_link && (
                  <a href={ev.html_link} target="_blank" rel="noopener noreferrer"
                    className="text-indigo-400 hover:text-indigo-300">Open ↗</a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      <button onClick={onReset} className="px-6 py-2.5 border border-gray-700 hover:border-gray-500 rounded-xl text-sm transition-colors">
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
      setStep("processing")
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Submission failed")
    }
  }

  const handleConfirm = async (tasks: Task[]) => {
    if (!session?.user?.email || !meetingId) return
    try {
      const r = await fetch("/api/calendar-sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meetingId, tasks }),
      })
      const data = await r.json()
      setEvents(data.events ?? [])
    } catch {
      setEvents([])
    }
    setStep("done")
  }

  const reset = () => {
    setStep("upload"); setMeetingId(""); setResult(null); setEvents([])
  }

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 size={32} className="animate-spin text-indigo-400" />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-8">
        <div className="text-center space-y-3">
          <div className="flex items-center justify-center gap-3 mb-4">
            <Mic size={32} className="text-indigo-400" />
            <h1 className="text-3xl font-bold">Meeting AI Agent</h1>
          </div>
          <p className="text-gray-400">Upload a meeting recording → get structured action items, auto-synced to Google Calendar.</p>
        </div>
        <button
          onClick={() => signIn("google")}
          className="flex items-center gap-3 px-6 py-3 bg-white text-gray-900 rounded-xl font-semibold hover:bg-gray-100 transition-colors"
        >
          <svg width="20" height="20" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
          </svg>
          Sign in with Google
        </button>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Mic size={20} className="text-indigo-400" />
          <span className="font-semibold">Meeting AI Agent</span>
        </div>
        <div className="flex items-center gap-3">
          {session.user?.image && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={session.user.image} alt="" className="w-7 h-7 rounded-full" />
          )}
          <span className="text-sm text-gray-400">{session.user?.email}</span>
          <button onClick={() => signOut()} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors">
            <LogOut size={15} />
            Sign out
          </button>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 flex justify-center px-4 py-10">
        <div className="w-full max-w-xl">
          <StepBar current={step} />

          {submitError && (
            <div className="mb-4 flex items-center gap-2 text-red-400 text-sm bg-red-950/30 border border-red-800 rounded-lg px-4 py-3">
              <AlertCircle size={16} /> {submitError}
            </div>
          )}

          {step === "upload" && <UploadStep onSubmit={handleSubmit} />}
          {step === "processing" && meetingId && (
            <ProcessingStep meetingId={meetingId} onDone={r => { setResult(r); setStep("review") }} />
          )}
          {step === "review" && result && (
            <ReviewStep result={result} onConfirm={handleConfirm} onSkip={() => setStep("done")} />
          )}
          {step === "done" && <DoneStep events={events} onReset={reset} />}
        </div>
      </main>
    </div>
  )
}

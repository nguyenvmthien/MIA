"use client"

import { useSession, signIn } from "next-auth/react"
import { useEffect, useState, useCallback } from "react"
import Link from "next/link"
import {
  ArrowLeft, Loader2, History, ChevronDown, ChevronUp,
  CheckCircle2, Clock, AlertCircle, Circle, Users, UserCheck,
  Calendar, FileAudio, X,
} from "lucide-react"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

// ── Types ─────────────────────────────────────────────────────────────────────

type MeetingSummary = {
  meeting_id: string
  status: string
  audio_filename: string | null
  created_at: string | null
  processed_at: string | null
  duration_ms: number | null
  summary_text: string | null
  participants: string[]
  task_count: number
  unresolved_speaker_count: number
  error: string | null
}

type Task = {
  task_id: string
  description: string
  assignee: string | null
  due_date: string | null
  priority: string
  status: string
  extraction_confidence: number
}

type ParticipantDetail = {
  speaker_id: string
  display_name: string
  worker_id: string | null
}

type MeetingDetail = {
  meeting_id: string
  status: string
  summary_text: string | null
  participants: string[]
  participants_detail: ParticipantDetail[]
  action_items: Task[]
  unresolved_items: Task[]
  human_review_items: Task[]
}

type Worker = { worker_id: string; name: string; role?: string | null }

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null) {
  if (!iso) return "—"
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  })
}

function fmtDuration(ms: number | null) {
  if (!ms) return null
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
    pending: "bg-amber-50 text-amber-700 border-amber-200",
    processing: "bg-sky-50 text-sky-700 border-sky-200",
    failed: "bg-red-50 text-red-700 border-red-200",
  }
  const icons: Record<string, React.ReactNode> = {
    completed: <CheckCircle2 size={11} />,
    pending: <Clock size={11} />,
    processing: <Loader2 size={11} className="animate-spin" />,
    failed: <AlertCircle size={11} />,
  }
  const cls = styles[status] ?? "bg-slate-100 text-slate-600 border-slate-200"
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full border ${cls}`}>
      {icons[status] ?? <Circle size={11} />}
      {status}
    </span>
  )
}

// ── Speaker resolution panel ───────────────────────────────────────────────────

function SpeakerResolver({
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
  const [resolving, setResolving] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)

  if (unresolved.length === 0) return null

  const resolve = async (speakerId: string, workerId: string) => {
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
    <div className="mt-4 bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2 text-amber-700 text-xs font-semibold">
        <UserCheck size={14} />
        {unresolved.length} unresolved speaker{unresolved.length > 1 ? "s" : ""} — assign to roster
      </div>
      {unresolved.map(p => (
        <div key={p.speaker_id} className="flex items-center gap-3">
          <span className="text-xs text-slate-700 font-mono bg-white border border-slate-200 px-2 py-1 rounded-md min-w-[100px]">
            {p.display_name}
          </span>
          <span className="text-slate-400 text-xs">→</span>
          <select
            value={resolving[p.speaker_id] ?? ""}
            onChange={e => setResolving(prev => ({ ...prev, [p.speaker_id]: e.target.value }))}
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
            onClick={() => resolve(p.speaker_id, resolving[p.speaker_id])}
            disabled={!resolving[p.speaker_id] || saving === p.speaker_id}
            className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 rounded-lg text-xs font-medium text-white transition-colors flex items-center gap-1"
          >
            {saving === p.speaker_id ? <Loader2 size={11} className="animate-spin" /> : <UserCheck size={11} />}
            Assign
          </button>
        </div>
      ))}
    </div>
  )
}

// ── Meeting card ──────────────────────────────────────────────────────────────

function MeetingCard({ meeting, workers }: { meeting: MeetingSummary; workers: Worker[] }) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<MeetingDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const loadDetail = useCallback(async () => {
    if (detail) return
    setLoadingDetail(true)
    try {
      const r = await fetch(`${API}/meetings/${meeting.meeting_id}`)
      const data = await r.json()
      setDetail(data)
    } finally {
      setLoadingDetail(false)
    }
  }, [meeting.meeting_id, detail])

  const toggleExpand = () => {
    if (!expanded && meeting.status === "completed") loadDetail()
    setExpanded(e => !e)
  }

  const refreshDetail = async () => {
    setDetail(null)
    setLoadingDetail(true)
    try {
      const r = await fetch(`${API}/meetings/${meeting.meeting_id}`)
      setDetail(await r.json())
    } finally {
      setLoadingDetail(false)
    }
  }

  const priorityColors: Record<string, string> = {
    high: "text-red-400", critical: "text-red-400",
    medium: "text-amber-400", low: "text-emerald-400",
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm shadow-sky-900/5">
      {/* Card header */}
      <button
        onClick={toggleExpand}
        className="w-full flex items-start gap-4 px-4 py-4 text-left hover:bg-sky-50 transition-colors"
      >
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={meeting.status} />
            {meeting.unresolved_speaker_count > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full border bg-amber-50 text-amber-700 border-amber-200">
                <UserCheck size={11} />
                {meeting.unresolved_speaker_count} unresolved
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-600 flex-wrap">
            {meeting.audio_filename && (
              <span className="flex items-center gap-1 truncate max-w-[200px]">
                <FileAudio size={11} />
                {meeting.audio_filename}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Clock size={11} />
              {fmtDate(meeting.created_at)}
            </span>
            {meeting.duration_ms && (
              <span>{fmtDuration(meeting.duration_ms)}</span>
            )}
            {meeting.task_count > 0 && (
              <span className="flex items-center gap-1 text-sky-700">
                <Calendar size={11} />
                {meeting.task_count} task{meeting.task_count !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          {meeting.participants.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              <Users size={11} className="text-slate-400 flex-shrink-0" />
              {meeting.participants.map(p => (
                <span key={p} className="text-[11px] text-slate-600 bg-slate-100 border border-slate-200 px-1.5 py-0.5 rounded">{p}</span>
              ))}
            </div>
          )}
        </div>
        <div className="text-slate-400 flex-shrink-0 mt-1">
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-slate-200 px-4 pb-4 pt-3 space-y-4 bg-slate-50/60">
          {meeting.status === "failed" && meeting.error && (
            <div className="flex items-start gap-2 text-red-700 text-xs bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
              {meeting.error}
            </div>
          )}

          {meeting.summary_text && (
            <div className="text-sm text-slate-700 leading-relaxed border-l-2 border-sky-200 pl-3">
              {meeting.summary_text}
            </div>
          )}

          {loadingDetail && (
            <div className="flex items-center gap-2 text-slate-500 text-xs py-2">
              <Loader2 size={13} className="animate-spin" /> Loading details...
            </div>
          )}

          {detail && (
            <>
              {/* Speaker resolver */}
              {detail.participants_detail?.some(p => !p.worker_id) && (
                <SpeakerResolver
                  meetingId={meeting.meeting_id}
                  participants={detail.participants_detail}
                  workers={workers}
                  onResolved={refreshDetail}
                />
              )}

              {/* Action items */}
              {detail.action_items.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                    Action Items ({detail.action_items.length})
                  </h4>
                  <div className="space-y-1.5">
                    {detail.action_items.map(t => (
                      <div key={t.task_id} className={`flex items-start gap-3 rounded-lg px-3 py-2 border text-sm
                        ${t.status === "dismissed"
                          ? "opacity-40 bg-slate-100 border-slate-200"
                          : "bg-white border-slate-200"}`}>
                        <div className="flex-1 min-w-0">
                          <p className={`text-slate-900 ${t.status === "dismissed" ? "line-through" : ""}`}>
                            {t.description}
                          </p>
                          <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                            {t.assignee && <span>👤 {t.assignee}</span>}
                            {t.due_date && <span>📅 {t.due_date}</span>}
                            {t.priority && (
                              <span className={priorityColors[t.priority] ?? "text-slate-400"}>
                                {t.priority}
                              </span>
                            )}
                          </div>
                        </div>
                        {t.extraction_confidence !== undefined && (
                          <span className={`text-[11px] flex-shrink-0 ${
                            t.extraction_confidence >= 0.8 ? "text-emerald-400"
                            : t.extraction_confidence >= 0.6 ? "text-amber-400"
                            : "text-red-400"}`}>
                            {Math.round(t.extraction_confidence * 100)}%
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Unresolved tasks */}
              {detail.unresolved_items.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    Unresolved Tasks ({detail.unresolved_items.length})
                  </h4>
                  <div className="space-y-1">
                    {detail.unresolved_items.map(t => (
                        <div key={t.task_id} className="flex items-start gap-3 rounded-lg px-3 py-2 bg-white border border-slate-200 text-sm opacity-80">
                          <p className="text-slate-700">{t.description}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const { data: session, status } = useSession()
  const [meetings, setMeetings] = useState<MeetingSummary[]>([])
  const [workers, setWorkers] = useState<Worker[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (status !== "authenticated") return
    Promise.all([
      fetch(`${API}/meetings`).then(r => r.json()),
      fetch(`${API}/workers`).then(r => r.json()),
    ]).then(([mData, wData]) => {
      setMeetings(mData.meetings ?? [])
      setWorkers(wData.workers ?? [])
    }).catch(() => setError("Failed to load data")).finally(() => setLoading(false))
  }, [status])

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 size={28} className="animate-spin text-sky-500" />
      </div>
    )
  }

  if (status === "unauthenticated") {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <p className="text-slate-600">Sign in to view meeting history.</p>
        <button onClick={() => signIn("google")}
          className="px-5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-sm font-medium transition-colors">
          Sign in with Google
        </button>
      </div>
    )
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <div className="max-w-2xl mx-auto px-4 py-10 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Link href="/" className="p-2 text-slate-500 hover:text-slate-900 transition-colors rounded-lg hover:bg-white border border-transparent hover:border-slate-200">
            <ArrowLeft size={18} />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
              <History size={20} className="text-sky-600" />
              Meeting History
            </h1>
            <p className="text-xs text-slate-500 mt-0.5">
              {session?.user?.email} · {meetings.length} meeting{meetings.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center justify-between bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            {error}
            <button onClick={() => setError(null)}><X size={14} /></button>
          </div>
        )}

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="animate-spin text-sky-500" />
          </div>
        ) : meetings.length === 0 ? (
          <div className="text-center py-20 text-slate-500 bg-white border border-slate-200 rounded-2xl">
            <History size={40} className="mx-auto mb-4 opacity-30 text-sky-500" />
            <p className="text-sm">No meetings yet.</p>
            <Link href="/" className="mt-3 inline-block text-xs text-sky-700 hover:text-sky-900 transition-colors">
              Upload your first meeting →
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {meetings.map(m => (
              <MeetingCard key={m.meeting_id} meeting={m} workers={workers} />
            ))}
          </div>
        )}
      </div>
    </main>
  )
}

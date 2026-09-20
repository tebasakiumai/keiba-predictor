import { useEffect, useState } from 'react'
import './index.css'

type Prediction = {
  rank: number
  umaban: number
  horse_name: string
  predicted_score: number
  odds: number | null
  popularity: number | null
}

type Race = {
  race_id: string
  race_name: string | null
  venue: string
  race_num: number
  post_time: string | null
  race_class: string
  course_type: string
  distance_m: number
  direction: string | null
  track_condition: string | null
  weather: string | null
  predictions: Prediction[]
}

type PredictionsData = {
  kaisai_date: string
  generated_at: string
  races: Race[]
}

function useTheme() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = localStorage.getItem('theme')
    return saved === 'dark' || saved === 'light' ? saved : 'dark'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  return { theme, toggleTheme: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) }
}

function markForRank(rank: number): string {
  if (rank === 1) return '◎'
  if (rank === 2) return '○'
  if (rank === 3) return '▲'
  return ''
}

function formatKaisaiDate(yyyymmdd: string): string {
  const y = yyyymmdd.slice(0, 4)
  const m = yyyymmdd.slice(4, 6)
  const d = yyyymmdd.slice(6, 8)
  return `${y}年${m}月${d}日`
}

function RaceCard({ race }: { race: Race }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="card race-card">
      <button className="race-card-header" onClick={() => setOpen((o) => !o)}>
        <div>
          <span className="tag">{race.venue}{race.race_num}R</span>{' '}
          <span className="tag tag-accent">{race.race_class}</span>
          {race.race_name && race.race_name !== race.race_class && (
            <div className="race-card-name">{race.race_name}</div>
          )}
        </div>
        <div className="race-card-sub mono">
          {race.course_type}{race.distance_m}m
          {race.direction ? `(${race.direction})` : ''}
          {race.weather ? ` / 天候:${race.weather}` : ''}
          {race.track_condition ? ` / 馬場:${race.track_condition}` : ''}
          {race.post_time ? ` / ${race.post_time}発走` : ''}
        </div>
        <span className="race-card-toggle">{open ? '－' : '＋'}</span>
      </button>

      {open && (
        <div className="race-card-body">
          {race.predictions.map((p) => (
            <div key={p.umaban} className="prediction-row mono">
              <span className="prediction-rank">{p.rank}</span>
              <span className="prediction-mark">{markForRank(p.rank)}</span>
              <span className="prediction-umaban">{p.umaban}</span>
              <span className="prediction-name">{p.horse_name}</span>
              <span className="prediction-odds">
                {p.odds != null ? `${p.odds}倍` : '-'}
                {p.popularity != null ? ` (${p.popularity}人気)` : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function App() {
  const { theme, toggleTheme } = useTheme()
  const [data, setData] = useState<PredictionsData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
      fetch(`${import.meta.env.BASE_URL}predictions.json`)
      .then((res) => {
        if (!res.ok) throw new Error(`status ${res.status}`)
        return res.json()
      })
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <>
      <header className="site-header">
        <span className="site-logo mono">keiba-predictor</span>
        <div className="site-header-right">
          <button className="theme-toggle" onClick={toggleTheme}>
            {theme === 'dark' ? 'LIGHT' : 'DARK'}
          </button>
        </div>
      </header>

      <main className="races-section">
        <h1 className="races-title">今週の予測</h1>
        {data && (
          <p className="races-meta mono">
            対象日: {formatKaisaiDate(data.kaisai_date)}
            {' / '}
            生成日時: {new Date(data.generated_at).toLocaleString('ja-JP')}
          </p>
        )}

        {error && <p className="race-card-sub">読み込みに失敗しました: {error}</p>}
        {!data && !error && <p className="race-card-sub">読み込み中...</p>}

        {data && (
          <div className="races-list">
            {data.races.map((race) => (
              <RaceCard key={race.race_id} race={race} />
            ))}
          </div>
        )}
      </main>
    </>
  )
}

export default App

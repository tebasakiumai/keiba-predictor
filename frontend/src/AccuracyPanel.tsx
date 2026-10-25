import { useEffect, useState } from 'react'
import './accuracy.css'

type Rates = { win: number; place: number; overlap: number; trio: number }
type Paired = { only_model: number; only_favorite: number; p_value: number }

type AccuracyData = {
  generated_at: string
  date_from: string
  date_to: string
  overall: {
    n_races: number
    model: Rates
    favorite: Rates
    random: { win: number; place: number }
    paired: { win: Paired; place: Paired }
  }
}

function formatDate(yyyymmdd: string): string {
  return `${yyyymmdd.slice(0, 4)}/${yyyymmdd.slice(4, 6)}/${yyyymmdd.slice(6, 8)}`
}

const pct = (x: number) => `${(x * 100).toFixed(1)}%`

export default function AccuracyPanel() {
  const [data, setData] = useState<AccuracyData | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}accuracy.json`)
      .then((res) => {
        if (!res.ok) throw new Error(`status ${res.status}`)
        return res.json()
      })
      .then(setData)
      .catch(() => setMissing(true))
  }, [])

  if (missing) return null
  if (!data) return null

  const { overall: o } = data
  const significant = Math.min(o.paired.win.p_value, o.paired.place.p_value) < 0.05

  return (
    <section className="acc-section">
      <h2 className="acc-title">モデルの実績</h2>
      <p className="acc-meta mono">
        {formatDate(data.date_from)} 〜 {formatDate(data.date_to)} / {o.n_races}レース /
        学習に使っていない期間での検証
      </p>

      <div className="card acc-card">
        <table className="acc-table mono">
          <thead>
            <tr>
              <th></th>
              <th>モデル</th>
              <th>1番人気</th>
              <th>ランダム</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>◎ 単勝率</td>
              <td>{pct(o.model.win)}</td>
              <td>{pct(o.favorite.win)}</td>
              <td className="acc-muted">{pct(o.random.win)}</td>
            </tr>
            <tr>
              <td>◎ 複勝率</td>
              <td>{pct(o.model.place)}</td>
              <td>{pct(o.favorite.place)}</td>
              <td className="acc-muted">{pct(o.random.place)}</td>
            </tr>
            <tr>
              <td>上位3頭の一致数</td>
              <td>{o.model.overlap.toFixed(2)}</td>
              <td>{o.favorite.overlap.toFixed(2)}</td>
              <td className="acc-muted">-</td>
            </tr>
            <tr>
              <td>三連複率</td>
              <td>{pct(o.model.trio)}</td>
              <td>{pct(o.favorite.trio)}</td>
              <td className="acc-muted">-</td>
            </tr>
          </tbody>
        </table>

        <p className="acc-note">
          {significant
            ? '1番人気との差は、統計的に有意な水準に達しています。'
            : '現時点では、1番人気との差は統計的に有意ではありません(母数が少ないため、数%の差は偶然でも起こります)。'}
        </p>
        <p className="acc-note">
          ◎=予想1位。1番人気は、予測時点のオッズが最小の馬。上位3頭の一致数は、予想1〜3位のうち実際に3着以内に入った頭数の平均(0〜3)です。
        </p>
      </div>
    </section>
  )
}

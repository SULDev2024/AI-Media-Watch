import type { ExtractedEntities } from '../api/types'

interface Props {
  entities: ExtractedEntities
}

function Group({ label, items, color }: { label: string; items: string[]; color: string }) {
  if (items.length === 0) return null
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <div className="flex flex-wrap gap-1">
        {items.map((v, i) => (
          <span
            key={i}
            className={`inline-block rounded px-2 py-0.5 text-xs font-mono ${color}`}
          >
            {v}
          </span>
        ))}
      </div>
    </div>
  )
}

export function EntityChips({ entities }: Props) {
  const hasAny = Object.values(entities).some((arr) =>
    Array.isArray(arr) && arr.length > 0,
  )

  if (!hasAny) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Entities</p>
        <p className="text-xs text-gray-400">No entities extracted</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Entities</p>
      <Group label="Telegram handles" items={entities.telegram_handles} color="bg-blue-50 text-blue-700" />
      <Group label="Crypto wallets"   items={entities.crypto_wallets}   color="bg-orange-50 text-orange-700" />
      <Group label="Phone numbers"    items={entities.phone_numbers}    color="bg-purple-50 text-purple-700" />
      <Group label="Payment phones"   items={entities.payment_phones}   color="bg-red-50 text-red-700" />
      <Group label="Profit claims"    items={entities.profit_claims}    color="bg-yellow-50 text-yellow-800" />
      <Group label="Referral codes"   items={entities.referral_codes}   color="bg-green-50 text-green-700" />
      <Group label="Websites"         items={entities.websites}         color="bg-gray-100 text-gray-700" />
      <Group label="Telegram links"   items={entities.telegram_links}   color="bg-sky-50 text-sky-700" />
    </div>
  )
}

import { useMemo, useState } from "react";
import type { PresetProps } from "../AppShell";
import { cn, formatCell, type Row } from "../lib/data";

/** Field roles the card layout fills. Each can be pinned with a mapping slot
 * of the same name (e.g. {image: "thumbnail", price: "price_usd"}); unpinned
 * roles are inferred from the field names and values of the first rows. */
interface Roles {
  image: string | null;
  title: string | null;
  subtitle: string | null;
  price: string | null;
  rating: string | null;
  badge: string | null;
}

const IMAGE_URL = /^https?:\/\/\S+\.(?:png|jpe?g|webp|gif|avif|svg)(?:[?#]\S*)?$/i;
const IMAGE_NAME = /(thumbnail|image|img|photo|picture|avatar|logo|cover)/i;
const TITLE_NAMES = ["title", "name", "product_name", "full_name", "label", "username", "firstname"];
const SUBTITLE_NAME = /^(brand|category|type|subtitle|kind|genre|cuisine|region|company|vendor)$/i;
const PRICE_NAME = /(price|amount|cost|total|fee)/i;
const RATING_NAME = /^(rating|stars|score|avg_rating|average_rating)$/i;
const BADGE_NAME = /(stock|availability|status|inventory)/i;

function inferRoles(rows: Row[], mapping: Record<string, string>): Roles {
  const keys = Object.keys(rows[0] ?? {});
  const sample = rows.slice(0, 5);
  const pinned = (slot: string) => (mapping[slot] && keys.includes(mapping[slot]) ? mapping[slot] : null);
  const isImage = (k: string) =>
    sample.some((r) => typeof r[k] === "string" && IMAGE_URL.test(r[k] as string)) ||
    (IMAGE_NAME.test(k) && sample.some((r) => typeof r[k] === "string" && /^https?:\/\//.test(r[k] as string)));
  const numeric = (k: string) => sample.some((r) => typeof r[k] === "number");
  const title =
    pinned("title") ??
    TITLE_NAMES.map((n) => keys.find((k) => k.toLowerCase() === n)).find(Boolean) ??
    keys.find((k) => typeof rows[0]?.[k] === "string" && !isImage(k)) ??
    null;
  return {
    image: pinned("image") ?? keys.find(isImage) ?? null,
    title,
    subtitle: pinned("subtitle") ?? keys.find((k) => k !== title && SUBTITLE_NAME.test(k)) ?? null,
    price: pinned("price") ?? keys.find((k) => PRICE_NAME.test(k) && numeric(k)) ?? null,
    rating: pinned("rating") ?? keys.find((k) => RATING_NAME.test(k) && numeric(k)) ?? null,
    badge: pinned("badge") ?? keys.find((k) => BADGE_NAME.test(k)) ?? null,
  };
}

/** True when rows look like a catalog worth laying out as cards. */
export function looksLikeCards(rows: Row[]): boolean {
  if (rows.length === 0 || rows.length > 24) return false;
  const roles = inferRoles(rows, {});
  return Boolean(roles.image && roles.title);
}

function formatPrice(value: unknown, currency: string | undefined): string {
  if (typeof value !== "number") return formatCell(value);
  if (currency && /^[A-Z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(value);
    } catch {
      /* unknown code — fall through to a plain number */
    }
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function badgeText(field: string, value: unknown): string {
  if (typeof value === "number" && /stock|inventory/i.test(field)) {
    return value > 0 ? `${value} in stock` : "Out of stock";
  }
  return formatCell(value);
}

/** Branded item cards — image, title, subtitle, price, rating, badge — for
 * catalogs and listings. Picking a card tells the model which item the user
 * chose, so "the second one" needs no re-reading of the list. */
export function CardsPreset({ config, data, onContext }: PresetProps) {
  const [picked, setPicked] = useState<number | null>(null);
  const roles = useMemo(() => inferRoles(data.rows, config.mapping), [data.rows, config.mapping]);
  const currency = config.mapping["currency"];

  if (data.rows.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">{data.emptyNote ?? "Nothing found."}</p>;
  }

  const single = data.rows.length === 1;
  return (
    <ul
      className={cn(
        "grid gap-3 p-4",
        single ? "grid-cols-1" : "[grid-template-columns:repeat(auto-fill,minmax(11rem,1fr))]"
      )}
    >
      {data.rows.map((row, i) => {
        const title = roles.title ? formatCell(row[roles.title]) : `Item ${i + 1}`;
        const image = roles.image && typeof row[roles.image] === "string" ? (row[roles.image] as string) : null;
        const rating = roles.rating ? row[roles.rating] : null;
        const isPicked = picked === i;
        return (
          <li key={i}>
            <article
              className={cn(
                "flex h-full overflow-hidden rounded-lg border bg-card transition-shadow",
                single ? "flex-row" : "flex-col",
                isPicked ? "border-primary ring-2 ring-primary/30" : "border-border hover:shadow-sm"
              )}
            >
              {image && (
                <div className={cn("shrink-0 bg-muted", single ? "w-36" : "aspect-[4/3] w-full")}>
                  <img
                    src={image}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover"
                    onError={(e) => {
                      (e.currentTarget.parentElement as HTMLElement).style.display = "none";
                    }}
                  />
                </div>
              )}
              <div className="flex min-w-0 flex-1 flex-col gap-1.5 p-3">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold" title={title}>
                    {title}
                  </h3>
                  {roles.subtitle && row[roles.subtitle] != null && (
                    <p className="truncate text-2xs text-muted-foreground">{formatCell(row[roles.subtitle])}</p>
                  )}
                </div>
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  {roles.price && row[roles.price] != null && (
                    <span className="text-base font-bold tabular-nums">
                      {formatPrice(row[roles.price], currency)}
                    </span>
                  )}
                  {typeof rating === "number" && (
                    <span className="text-2xs text-muted-foreground tabular-nums">
                      ★ {rating.toFixed(1)}
                    </span>
                  )}
                </div>
                {roles.badge && row[roles.badge] != null && (
                  <span className="w-fit rounded-full bg-muted px-2 py-0.5 text-2xs text-muted-foreground">
                    {badgeText(roles.badge, row[roles.badge])}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setPicked(i);
                    onContext(`In the ${config.title} view the user picked: ${JSON.stringify(row)}`, {
                      picked_item: row,
                    });
                  }}
                  className={cn(
                    "mt-auto rounded px-3 py-1.5 text-xs font-medium transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
                    isPicked
                      ? "bg-primary text-primary-foreground"
                      : "border border-border bg-background hover:border-primary/50"
                  )}
                >
                  {isPicked ? "Selected" : "Choose"}
                </button>
              </div>
            </article>
          </li>
        );
      })}
    </ul>
  );
}

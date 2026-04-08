from typing import Any

from playwright.async_api import Page

_BUILD_JS = """
(() => {
  const sel = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [tabindex]:not([tabindex="-1"])';
  const seen = new Set();
  const nodes = [];
  document.querySelectorAll(sel).forEach(el => {
    if (seen.has(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    let p = el;
    while (p && p !== document.body) {
      if (p.hidden || (p instanceof HTMLElement && p.getAttribute('aria-hidden') === 'true')) return;
      p = p.parentElement;
    }
    seen.add(el);
    nodes.push(el);
  });
  let ref = 1;
  const lines = [];
  nodes.forEach(el => {
    el.setAttribute('data-agent-ref', String(ref));
    const tag = el.tagName.toLowerCase();
    let label = '';
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) {
      label = el.name || el.id || el.placeholder || el.type || '';
    } else {
      label = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
    }
    label = label.replace(/\\s+/g, ' ').slice(0, 120);
    const role = el.getAttribute('role') || '';
    lines.push(`[ref=${ref}] <${tag}${role ? ' role=' + role : ''}> ${label}`);
    ref++;
  });
  return { lines, count: nodes.length };
})()
"""

_MAX_CHARS = 48_000


class PageContextBuilder:
    @staticmethod
    async def build(page: Page) -> str:
        data: dict[str, Any] = await page.evaluate(_BUILD_JS)
        lines: list[str] = data.get("lines") or []
        title = await page.title()
        url = page.url
        body = "\n".join(lines)
        outline = f"URL: {url}\nTitle: {title}\nInteractive elements ({data.get('count', 0)}):\n{body}"
        if len(outline) > _MAX_CHARS:
            outline = outline[:_MAX_CHARS] + "\n\n[truncated]"
        return outline

    @staticmethod
    async def build_aria_snapshot(page: Page) -> str:
        title = await page.title()
        url = page.url
        snap = await page.locator("html").aria_snapshot()
        outline = f"URL: {url}\nTitle: {title}\nARIA snapshot:\n{snap}"
        if len(outline) > _MAX_CHARS:
            outline = outline[:_MAX_CHARS] + "\n\n[truncated]"
        return outline

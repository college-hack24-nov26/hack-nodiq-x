/**
 * formatRichText — renders plain text containing light markdown
 * (**bold**, *italic*, `code`, - bullets, 1. numbered items, blank-line
 * paragraphs, | pipe tables |, --- rules) as professional React elements.
 *
 * Security: output is plain React nodes — never dangerouslySetInnerHTML —
 * so model/user text can never inject HTML or scripts. **bold** segments
 * are additionally stripped of characters like "<" before rendering.
 */

const boldRe = /\*\*([^*]+)\*\*/;
const italicRe = /(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/;
const codeRe = /`([^`\n]+)`/;

/** Render one line's inline markdown (bold/italic/code) to React nodes. */
export function renderInline(text, keyPrefix = "i") {
  const parts = [];
  let rest = text;
  let k = 0;

  while (rest.length) {
    const b = boldRe.exec(rest);
    const it = italicRe.exec(rest);
    const c = codeRe.exec(rest);

    const candidates = [];
    if (b) candidates.push({ type: "bold", idx: b.index, len: b[0].length, m: b });
    if (it) candidates.push({ type: "italic", idx: it.index + it[1].length, len: it[2].length + 2, m: it });
    if (c) candidates.push({ type: "code", idx: c.index, len: c[0].length, m: c });

    if (!candidates.length) {
      parts.push(rest);
      break;
    }

    candidates.sort((a, x) => a.idx - x.idx);
    const hit = candidates[0];
    if (hit.idx > 0) parts.push(rest.slice(0, hit.idx));

    if (hit.type === "bold") {
      // strip angle brackets so bold text can never look like a tag
      parts.push(
        <strong key={`${keyPrefix}-${k++}`}>
          {hit.m[1].replace(/[<>]/g, "")}
        </strong>
      );
    } else if (hit.type === "italic") {
      parts.push(
        <em key={`${keyPrefix}-${k++}`}>{hit.m[2].replace(/[<>]/g, "")}</em>
      );
    } else {
      parts.push(<code key={`${keyPrefix}-${k++}`}>{hit.m[1]}</code>);
    }

    rest = rest.slice(hit.idx + hit.len);
  }

  return parts;
}

/** Split a markdown table row into cells (leading/trailing pipes tolerated). */
function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

/** True when the line is a markdown table separator like | --- | :---: |. */
function isTableSeparator(line) {
  return /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$/.test(line);
}

/** Markdown ATX heading ("### Title") → its level (1–6), or 0 when not one. */
function headingLevel(line) {
  const m = /^(#{1,6})\s+\S/.exec(line);
  return m ? m[1].length : 0;
}

/**
 * Render a full text block to professional paragraphs / lists / tables.
 * Consecutive "- " or "* " lines become a <ul>; "1. " lines an <ol>;
 * "| a | b |" runs become a <table> (with the separator row dropped);
 * blank lines separate paragraphs; "---" alone becomes a horizontal rule.
 */
export default function formatRichText(text, keyPrefix = "rt") {
  if (!text) return null;
  const lines = String(text).replace(/\r\n/g, "\n").split("\n");

  const blocks = [];
  let para = [];
  let list = [];
  let listType = null;
  let table = null;   // { header: [cells], rows: [[cells]] } | { rows } when headerless

  const flushPara = () => {
    if (para.length) {
      blocks.push({ type: "p", lines: para });
      para = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      blocks.push({ type: listType, items: list });
      list = [];
      listType = null;
    }
  };
  const flushTable = () => {
    if (table) {
      blocks.push(table);
      table = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const rule = /^\s*-{3,}\s*$/.test(line);
    const isTableLine = /^\s*\|.*\|\s*$/.test(line);
    const hLevel = headingLevel(line);

    if (isTableLine) {
      flushPara();
      flushList();
      const cells = splitTableRow(line);
      if (isTableSeparator(line)) {
        if (table && !table.header) table.header = null; // separator after headerless first row — ignore
      } else if (!table) {
        table = { type: "table", header: null, rows: [cells] };
      } else if (table.header === null && table.rows.length === 1) {
        // two body rows before any separator: treat the first as header
        table.header = table.rows[0];
        table.rows = [cells];
      } else {
        table.rows.push(cells);
      }
    } else if (rule && !para.length && !list.length) {
      flushTable();
      blocks.push({ type: "hr" });
    } else if (hLevel) {
      flushPara();
      flushList();
      flushTable();
      // demote in-page headings to h4–h6: the page's own h1–h3 must stay
      // visually dominant over anything inside a chat answer / report body
      blocks.push({ type: "h", level: Math.min(hLevel + 3, 6), text: line.replace(/^#{1,6}\s+/, "") });
    } else if (bullet) {
      flushPara();
      flushTable();
      if (listType !== "ul") flushList();
      listType = "ul";
      list.push(bullet[1]);
    } else if (numbered) {
      flushPara();
      flushTable();
      if (listType !== "ol") flushList();
      listType = "ol";
      list.push(numbered[1]);
    } else if (!line.trim()) {
      flushPara();
      flushList();
      flushTable();
    } else {
      flushPara();
      flushList();
      flushTable();
      para.push(line);
    }
  }
  flushPara();
  flushList();
  flushTable();

  return blocks.map((b, i) => {
    const key = `${keyPrefix}-${i}`;
    if (b.type === "p") {
      return <p key={key}>{renderInline(b.lines.join(" "), key)}</p>;
    }
    if (b.type === "h") {
      const H = `h${b.level}`;
      return <H key={key} className="rich-heading">{renderInline(b.text, key)}</H>;
    }
    if (b.type === "hr") {
      return <hr key={key} className="rich-hr" />;
    }
    if (b.type === "table") {
      const cell = (content, j) => renderInline(content, `${key}-${j}`);
      return (
        <div key={key} className="rich-table-wrap">
          <table className="rich-table">
            {b.header && (
              <thead>
                <tr>{b.header.map((c, j) => <th key={j}>{cell(c, j)}</th>)}</tr>
              </thead>
            )}
            <tbody>
              {b.rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, j) => <td key={j}>{cell(c, j)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    const items = b.items.map((item, j) => (
      <li key={`${key}-${j}`}>{renderInline(item, `${key}-${j}`)}</li>
    ));
    return b.type === "ul" ? <ul key={key}>{items}</ul> : <ol key={key}>{items}</ol>;
  });
}

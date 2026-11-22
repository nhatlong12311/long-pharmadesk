/* PharmaCount: isolate large XLSX catalog parsing from the counting UI. */
"use strict";
self.onmessage = (event) => {
  try {
    self.postMessage({ type: "progress", message: "Đang đọc Excel trong luồng riêng..." });
    importScripts("https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js");
    const { buffer, codes } = event.data;
    const normalize = (value) => String(value ?? "").normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d")
      .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const sourceCodes = new Set(codes.map(normalize));
    const index = (row, aliases) => {
      const values = row.map(normalize);
      let n = values.findIndex(v => aliases.some(a => v === a));
      if (n < 0) n = values.findIndex(v => aliases.some(a => v.includes(a) && v.length < a.length + 15));
      return n;
    };
    const book = XLSX.read(buffer, { type: "array", cellDates: false, bookVBA: false });
    const result = [];
    let scanned = 0;
    let identifiedSheets = 0;
    for (let si = 0; si < book.SheetNames.length; si++) {
      const sheetName = book.SheetNames[si];
      const sheet = book.Sheets[sheetName];
      if (!sheet?.["!ref"]) continue;
      self.postMessage({ type: "progress", message: "Đang kiểm tra " + sheetName + " (" + (si + 1) + "/" + book.SheetNames.length + ")" });
      const r = XLSX.utils.decode_range(sheet["!ref"]);
      const rows = XLSX.utils.sheet_to_json(sheet, {
        header: 1, raw: true, defval: "", blankrows: false,
        range: { s: { r: 0, c: 0 }, e: { r: r.e.r, c: Math.min(r.e.c, 20) } }
      });
      const codeCols = ["ma", "ma duoc", "ma thuoc", "ma hang", "ma san pham", "ma vat tu"];
      const packCols = ["quy cach dong goi", "quy cach", "dong goi"];
      let header = -1;
      for (let i = 0; i < Math.min(100, rows.length); i++) {
        const line = rows[i];
        if (Array.isArray(line) && index(line, codeCols) >= 0 && index(line, packCols) >= 0) {
          header = i; break;
        }
      }
      if (header < 0) continue;
      identifiedSheets++;
      const title = rows[header], codeColumn = index(title, codeCols),
        packColumn = index(title, packCols),
        nameColumn = index(title, ["ten thuoc", "ten duoc", "ten duoc vtyt hc", "ten hang"]),
        unitColumn = index(title, ["dvt", "don vi tinh", "don vi"]),
        factorColumn = index(title, ["he so quy doi", "vien hop", "so vien hop", "so don vi hop"]);
      for (let i = header + 1; i < rows.length; i++) {
        const line = rows[i];
        if (!Array.isArray(line)) continue;
        const code = String(line[codeColumn] ?? "").trim();
        if (!code) continue;
        scanned++;
        if (!sourceCodes.has(normalize(code))) continue;
        const packText = String(line[packColumn] ?? "").trim();
        let factor = 0;
        const explicit = factorColumn < 0 ? NaN : Number(line[factorColumn]);
        if (Number.isSafeInteger(explicit) && explicit > 0) factor = explicit;
        else {
          const compact = normalize(packText);
          const products = Array.from(compact.matchAll(/(\d+)\s*vi\s*x\s*(\d+)\s*vien/g), m => Number(m[1]) * Number(m[2]));
          const directs = Array.from(compact.matchAll(/(?:hop|thung)\s*(\d+)\s*(?:vien|lo|ong|chai|goi)/g), m => Number(m[1]));
          const candidates = [...new Set([...products, ...directs].filter(n => Number.isSafeInteger(n) && n > 0))];
          if (candidates.length === 1 && !/[;,]|\bhoac\b/.test(compact)) factor = candidates[0];
        }
        result.push({
          code, name: nameColumn < 0 ? "" : String(line[nameColumn] ?? ""),
          unit: unitColumn < 0 ? "" : String(line[unitColumn] ?? ""),
          packText, factor, sheet: sheetName, row: i + 1
        });
      }
    }
    self.postMessage({ type: "done", entries: result, scanned, identifiedSheets });
  } catch (error) {
    self.postMessage({ type: "error", message: String(error?.message || error) });
  }
};

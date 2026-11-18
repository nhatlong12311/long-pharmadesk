const assert = require("node:assert/strict");
const { createReadStream } = require("node:fs");
const { readFile } = require("node:fs/promises");
const { createServer } = require("node:http");
const { extname, resolve, sep } = require("node:path");
const { chromium } = require("playwright");

const root = resolve(process.argv[2]);
const xlsx = require(resolve(root, "xlsx.full.min.js"));
const prefix = "/long-pharmadesk/";
const mime = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".wasm": "application/wasm",
};

function serve(request, response) {
  const path = new URL(request.url, "http://localhost").pathname;
  if (!path.startsWith(prefix)) {
    response.writeHead(404).end();
    return;
  }
  const file = resolve(root, decodeURIComponent(path.slice(prefix.length)) || "index.html");
  if (!file.startsWith(root + sep)) {
    response.writeHead(404).end();
    return;
  }
  const stream = createReadStream(file);
  stream.on("error", () => response.writeHead(404).end());
  stream.on("open", () => {
    response.setHeader("Content-Type", mime[extname(file)] || "application/octet-stream");
    stream.pipe(response);
  });
}

function workbook(rows, bookType = "xlsx") {
  const book = xlsx.utils.book_new();
  xlsx.utils.book_append_sheet(book, xlsx.utils.aoa_to_sheet(rows), "Dữ liệu giả");
  return xlsx.write(book, {bookType, type: "base64"});
}

async function api(page, path, {data, file, field = "file", opts, filename = "synthetic.xlsx"} = {}) {
  const results = await page.evaluate(async ({path, data, file, field, opts, filename}) => {
    let options;
    if (file) {
      const form = new FormData();
      form.append(field, new Blob([Uint8Array.from(atob(file), c => c.charCodeAt(0))]), filename);
      if (opts) form.append("opts", JSON.stringify(opts));
      options = {method: "POST", body: form};
    } else if (data) {
      options = {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)};
    }
    const response = await fetch(path, options);
    return {status: response.status, value: await response.json()};
  }, {path, data, file, field, opts, filename});
  assert.equal(results.status, 200, JSON.stringify(results.value));
  assert.notEqual(results.value.ok, false, JSON.stringify(results.value));
  return results.value;
}

async function assertDownload(page, action, filename, signature) {
  const event = page.waitForEvent("download");
  await action();
  const download = await event;
  assert.match(download.suggestedFilename(), filename);
  const content = await readFile(await download.path());
  assert.ok(content.includes(Buffer.from(signature)), download.suggestedFilename());
}

async function main() {
  const server = createServer(serve);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const site = origin + prefix;
  let browser;
  try {
    browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH});
    const context = await browser.newContext({acceptDownloads: true});
    const unexpected = [];
    await context.route("**/*", route => {
      const url = route.request().url();
      if (!/^https?:/.test(url) || url.startsWith(site)) return route.continue();
      unexpected.push(url);
      return route.abort();
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    let allowStartup;
    const pauseStartup = new Promise(resolve => { allowStartup = resolve; });
    await page.route("**/python.zip", async route => {
      await pauseStartup;
      await route.continue();
    }, {times:1});
    await page.goto(site + "?module=adr");
    const description = page.locator('[data-ap="mo_ta"]');
    await description.fill("Nội dung giả nhập trong lúc Python đang tải.");
    assert.equal(await page.locator("#adrGo").isEnabled(), false);
    assert.equal(await page.locator("#adrForm .adr-drug").count(), 4);
    assert.equal(await page.locator("#adrForm .adr-con").count(), 10);
    const startupBounds = await page.locator("#localStatus").boundingBox();
    const formBounds = await page.locator("#adrMain").boundingBox();
    assert.ok(startupBounds.y + startupBounds.height <= formBounds.y);

    const sidebar = page.locator("header");
    for (const expanded of [false, true, false]) {
      if ((await page.locator("#sidebarToggle").getAttribute("aria-pressed") === "true") !== expanded) {
        await page.locator("#sidebarToggle").click();
      }
      await page.locator("#tabAdr").hover();
      const nav = await sidebar.boundingBox();
      assert.ok((await page.locator("#adrMain").boundingBox()).x >= nav.x + nav.width);
      assert.ok(await page.locator("#tabAbc").isVisible());
    }
    allowStartup();
    await page.waitForFunction(() => !document.querySelector("#adrGo").disabled);
    assert.equal(await description.evaluate(input => input.value), "Nội dung giả nhập trong lúc Python đang tải.");
    console.log("ADR starts before Python is ready and the sidebar stays outside the form");

    await page.locator("#tabAbc").click();
    await page.waitForFunction(() => document.querySelector("#abcM").value && document.querySelector("#localStatus").hidden);
    assert.equal(await page.locator("#tabGop").isVisible(), false);
    assert.equal(await page.locator("#tabTru").isVisible(), false);
    assert.equal(await page.locator('a[href*="onrender.com"]').count(), 0);

    const rows = [
      ["Mã dược","Tên thuốc","Hoạt chất","Hàm lượng","Quy cách","VEN","ĐVT","Đơn giá","Số lượng","Thành tiền"],
      ["SYN01","Mẫu A","Chất A","10mg","Hộp 10","V","Viên",100,10,1000],
      ["SYN02","Mẫu B","Chất B","10mg","Hộp 20","E","Viên",50,4,200],
      ["SYN03","Mẫu A","Chất A","10mg","Hộp 20","V","Viên",150,2,300],
    ];
    const file = workbook(rows);
    const oldExcel = await api(page, "/api/abc/inspect", {file: workbook(rows, "biff8"), filename: "synthetic.xls"});
    assert.equal(oldExcel.rows, 3);
    const opts = {month: 11, year: 2026, mode: "calc", a: 78, b: 95};
    for (const [path, extension, member] of [
      ["export-month", /\.xlsx$/, "xl/worksheets/sheet1.xml"],
      ["generate", /\.docx$/, "word/document.xml"],
    ]) {
      const result = await api(page, `/api/abc/${path}`, {file, field:"cur", opts});
      await assertDownload(page, () => page.evaluate(name => downloadReport("/api/abc/download?name=" + encodeURIComponent(name), name), result.name), extension, member);
    }
    console.log("ABC/VEN: Excel input and Excel/Word downloads");

    const rules = await api(page, "/api/ttt/state");
    assert.ok(rules.rules.pairs > 300);
    const prescription = workbook([
      ["MaBN","NgayChiDinh","MaHoatChat","Tên thuốc","Tên khoa"],
      ["SYN-PATIENT","18/11/2026","SYN01","Thuốc A","Kiểm thử"],
      ["SYN-PATIENT","18/11/2026","SYN02","Thuốc B","Kiểm thử"],
    ]);
    const interactions = await api(page, "/api/ttt/generate", {file: prescription, opts:{...opts, by_name:false, dmy:true}});
    await assertDownload(page, () => page.evaluate(name => downloadReport("/api/ttt/download?name=" + encodeURIComponent(name), name), interactions.name), /\.docx$/, "word/document.xml");
    console.log("Drug interactions: original rules and Word download");

    const sample = {age:60, weight:70, height:170};
    const vancomycin = await api(page, "/api/tdm/vanco/empiric", {data:{...sample, scr:1}});
    assert.ok(vancomycin.with_ld.auc0_24 > 0);
    const aminoglycoside = await api(page, "/api/tdm/amg/start", {data:{...sample, scr:100, dose:320, tau:24}});
    assert.ok(aminoglycoside.drugs.gentamicin);
    const vancoLevels = await api(page, "/api/tdm/vanco/two", {data:{
      dose1:1000, tinf1:1, tau:12, weight:70, t1:1, t2:6, c1:25, c2:10,
    }});
    assert.ok(vancoLevels.pk.cl > 0);
    const amgLevels = await api(page, "/api/tdm/amg/two", {data:{
      dose:320, tau:24, tinf:0.5, t1:1, t2:8, c1:14, c2:3,
    }});
    assert.ok(amgLevels.pk.cl > 0);
    console.log("TDM: vancomycin and aminoglycoside");

    await page.locator("#tabAdr").click();
    await page.locator('[data-ap="ten_bn"]').fill("MẪU THỬ");
    await page.locator('[data-ap="mo_ta"]').fill("Dữ liệu giả từ kiểm thử GitHub Pages.");
    await page.locator("#adrGo").click();
    await page.locator("#adrLocalPreview").waitFor();
    assert.match(await page.locator("#adrLocalPreview").getAttribute("src"), /^blob:/);
    await assertDownload(page, () => page.locator("#adrDownloadPdf").click(), /\.pdf$/, "%PDF-");
    await assertDownload(page, () => page.locator("#adrDownloadWord").click(), /\.docx$/, "word/document.xml");

    const draft = await api(page, "/api/adr/draft", {data:{data:{ten_bn:"MẪU THỬ", mo_ta:"Giả lập"}}});
    const second = await context.newPage();
    await second.goto(site + "?module=adr");
    await second.waitForFunction(name => Array.from(document.querySelector("#adrDraftSel").options).some(option => option.value === name), draft.name);
    await api(second, "/api/adr/draft/delete", {data:{name:draft.name}});
    await page.reload();
    const drafts = await api(page, "/api/adr/drafts");
    assert.equal(drafts.drafts.length, 0);
    console.log("ADR: PDF preview, PDF/Word downloads and draft persistence across tabs");

    await second.goto(site + "browser.html");
    await second.waitForFunction(() => window.XLSX && document.querySelector("#ruleInfo").textContent.includes("cặp"));

    await second.route("**/python.zip", route => route.abort(), {times:1});
    await second.goto(site + "?module=adr");
    await second.locator('[data-ap="mo_ta"]').fill("Dữ liệu giả giữ lại khi khởi động lại.");
    await second.locator("#localRetry").waitFor();
    await second.locator("#localRetry").click();
    await second.waitForFunction(() => !document.querySelector("#adrGo").disabled);
    assert.equal(await second.locator('[data-ap="mo_ta"]').evaluate(input => input.value),
      "Dữ liệu giả giữ lại khi khởi động lại.");
    console.log("The Python worker can be restarted without losing ADR input");

    assert.deepEqual(unexpected, [], "The app must send no requests outside the Pages site");
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

# -*- coding: utf-8 -*-
"""
Pharma Desk V2.8 - TDM Vancomycin & Aminoglycoside.
Chuyen cong thuc tu 2 file Excel (Chinh-lieu-Vancomycin, Aminoglycosid_BvTN) sang Python.
Mo hinh 1 ngan (one-compartment), truyen ngan (zero-order infusion) hoac bolus khi 6*Tinf <= T1/2 (nhu file Excel).
Tra ve so lieu + chuoi diem ve bieu do (JS ve bang SVG).
"""
import math

LN2 = math.log(2)


# ----------------------------------------------------------------------------- tien ich
def _f(v, name, lo=None, hi=None, default=None):
    if v in (None, ""):
        if default is not None:
            return float(default)
        raise ValueError(f"Thiếu giá trị: {name}")
    try:
        x = float(str(v).replace(",", "."))
    except ValueError:
        raise ValueError(f"Giá trị không hợp lệ: {name}")
    if not math.isfinite(x):
        raise ValueError(f"{name} phải là số hữu hạn.")
    if lo is not None and x < lo:
        raise ValueError(f"{name} phải ≥ {lo:g}")
    if hi is not None and x > hi:
        raise ValueError(f"{name} phải ≤ {hi:g}")
    return x


def mround(x, m):
    return m * math.floor(x / m + 0.5)


def infusion_time(dose):
    """Thoi gian truyen goi y theo lieu (toc do <= 1000 mg/h) - theo file Excel."""
    return 1 if dose <= 1000 else 1.5 if dose <= 1500 else 2 if dose <= 2000 else 2.5 if dose <= 2500 else 3


def is_bolus(tinf, t12):
    return 6 * tinf <= t12


def conc(t, doses, k, V, bolus, inclusive=True, t12=None):
    """Nong do tai thoi diem t = cong don cac lieu (ts, D, tinf). bolus: dua lieu tai ts; nguoc lai truyen deu."""
    cl = k * V
    c = 0.0
    for ts, D, tinf in doses:
        if t < ts or (t == ts and not inclusive):
            continue
        dt = t - ts
        dose_bolus = is_bolus(tinf, t12) if t12 is not None else bolus
        if dose_bolus or tinf <= 0:
            c += D / V * math.exp(-k * dt)
        elif dt <= tinf:
            c += D / (cl * tinf) * (1 - math.exp(-k * dt))
        else:
            c += D / (cl * tinf) * (1 - math.exp(-k * tinf)) * math.exp(-k * (dt - tinf))
    return c


def ss_values(D, tau, tinf, k, V, t12=None):
    """Dinh/day o trang thai on dinh (cong thuc Excel)."""
    if tau <= 0 or tinf < 0 or tinf > tau:
        raise ValueError('Thời gian truyền phải nằm trong khoảng cách giữa hai liều.')
    cl = k * V
    t12 = t12 or LN2 / k
    if is_bolus(tinf, t12):
        peak = D / (V * (1 - math.exp(-k * tau)))
        trough = peak * math.exp(-k * tau)
    else:
        peak = D * (1 - math.exp(-k * tinf)) / (cl * tinf * (1 - math.exp(-k * tau)))
        trough = peak * math.exp(-k * (tau - tinf))
    return peak, trough, D * 24 / (tau * cl)


def dose_auc(start, end, doses, k, V, t12):
    """Exact integral of the same per-dose bolus/infusion concentration model."""
    total = 0.0
    for ts, dose, tinf in doses:
        if end <= ts or end <= start:
            continue
        a, b = max(start, ts), end
        if tinf <= 0 or is_bolus(tinf, t12):
            total += dose / (V*k) * (math.exp(-k*(a-ts))-math.exp(-k*(b-ts)))
            continue
        scale = dose / (k*V*tinf)
        during_end = min(b, ts+tinf)
        if during_end > a:
            total += scale * ((during_end-a) +
                       (math.exp(-k*(during_end-ts))-math.exp(-k*(a-ts)))/k)
        after_start = max(a, ts+tinf)
        if b > after_start:
            total += scale * (-math.expm1(-k*tinf)) / k * (
                math.exp(-k*(after_start-ts-tinf))-math.exp(-k*(b-ts-tinf)))
    return total


def intervals(doses, k, V, t12, t_end):
    """Moi lieu -> khoang: peak, trough (truoc lieu ke), AUC khoang (cong thuc Excel). doses da sap theo ts."""
    out = []
    for i, (ts, D, tinf) in enumerate(doses):
        nxt = doses[i + 1][0] if i + 1 < len(doses) else t_end
        b = is_bolus(tinf, t12)
        pk = conc(ts + (0 if b else tinf), doses, k, V, b, t12=t12)
        tr = conc(nxt, doses, k, V, b, inclusive=False, t12=t12)
        out.append({"ts": ts, "dose": D, "tinf": tinf, "peak": pk, "trough": tr, "bolus": b, "end": nxt,
                    "auc": dose_auc(ts,nxt,doses,k,V,t12), "_model": (doses,k,V,t12)})
    return out


def window_auc(iv, tau, which):
    """Integrate a real 24-hour window relative to the first retained dose."""
    if not iv:
        return None
    start = iv[0]['ts'] + 24*which
    end = start + 24
    if end > max(r['end'] for r in iv) + 1e-9:
        return None
    return dose_auc(start, end, *iv[0]['_model'])


def curve(doses, k, V, t12, t_end, dt=0.1, t_from=0.0):
    """Duong cong nong do dày; moi khoang dung nhanh bolus/truyen theo Tinf cua lieu cua khoang do."""
    pts = []
    n = int(round((t_end - t_from) / dt))
    tl = sorted({round(t_from + i * dt, 6) for i in range(n + 1)} | {round(d[0], 6) for d in doses if t_from <= d[0] <= t_end})
    j = 0
    for t in tl:
        while j + 1 < len(doses) and doses[j + 1][0] <= t + 1e-9:
            j += 1
        # truoc lieu dau tien
        if t + 1e-9 < doses[0][0]:
            if pts:
                pts.append([round(t, 3), 0.0])
            continue
        b = is_bolus(doses[j][2], t12)
        # diem ngay truoc lieu (de thay nhay bac khi bolus)
        if b and t > t_from and any(abs(t - d[0]) < 1e-9 for d in doses):
            pts.append([round(t, 3), round(conc(t, doses, k, V, b, inclusive=False, t12=t12), 4)])
        pts.append([round(t, 3), round(conc(t, doses, k, V, b, t12=t12), 4)])
    return pts


def n_back(k, tau):
    """So lieu truoc do can mo phong de dat trang thai on dinh (phan con lai < 1e-12)."""
    return max(8, min(600, math.ceil(27.6 / (k * tau)) + 1))


def status(v, lo=None, hi=None):
    if v is None:
        return None
    if hi is not None and v > hi:
        return "high"
    if lo is not None and v < lo:
        return "low"
    return "ok"


# ----------------------------------------------------------------------------- Vancomycin: lieu khoi dau
def vanco_empiric(p):
    age = _f(p.get("age"), "Tuổi", 1, 120)
    male = str(p.get("sex", "M")).upper().startswith("M")
    w = _f(p.get("weight"), "Cân nặng thực", 10, 300)
    h = _f(p.get("height"), "Chiều cao", 100, 230)
    scr = _f(p.get("scr"), "Creatinin máu (mg/dL)", 0.1, 20)
    vdkg = _f(p.get("vd_kg"), "Vd (L/kg)", 0.2, 2, default=0.7)
    auc_t = _f(p.get("target_auc"), "AUC24 mục tiêu", 100, 1000, default=500)
    thr_pk = _f(p.get("thr_peak"), "Ngưỡng đỉnh", 1, 200, default=40)
    thr_tr = _f(p.get("thr_trough"), "Ngưỡng đáy", 0.1, 100, default=15)
    hours = _f(p.get("hours"), "Số giờ vẽ", 12, 168, default=48)

    ibw = (50 if male else 45.5) + 2.3 * (h - 152.4) / 2.54
    pct = 100 * w / ibw
    if pct <= 75:
        cond, wt = "Suy kiệt (≤75% IBW)", 1.13 * w
    elif pct < 100:
        cond, wt = "Thiếu cân (75–100% IBW)", w
    elif pct > 120:
        cond, wt = "Béo phì (>120% IBW)", ibw + 0.4 * (w - ibw)
    else:
        cond, wt = "Bình thường (100–120% IBW)", ibw
    crcl = (140 - age) * wt / (72 * scr) * (1 if male else 0.85)
    V = vdkg * w
    CL = (crcl * 0.689 + 3.66) * 0.06
    k = CL / V
    t12 = LN2 / k
    tau = 6 if 4 < t12 <= 5 else 8 if t12 <= 8 else 12 if t12 <= 12 else 24 if t12 <= 24 else 48
    tau_text = "6 giờ" if 4 < t12 <= 5 else "8 – 12 giờ" if t12 <= 8 else "12 – 24 giờ" if t12 <= 12 else "24 – 48 giờ" if t12 <= 24 else "≥ 48 giờ"
    md = mround(auc_t * CL * tau / 24, 250)
    if md <= 0:
        raise ValueError("Liều duy trì tính ra bằng 0 - kiểm tra lại số liệu.")
    t_md = infusion_time(md)
    pk_ss = ss_values(md, tau, t_md, k, V, t12)[0]
    ld = min(mround(V * pk_ss, 250), 3000)
    t_ld = infusion_time(ld)

    def regimen(ld_dose, ld_t, md_dose, md_t, tau_):
        doses, t = [], 0.0
        if ld_dose:
            doses.append((0.0, ld_dose, ld_t))
            t = tau_
        while t <= hours + 1e-9:
            doses.append((t, md_dose, md_t))
            t += tau_
        iv = intervals(doses, k, V, t12, doses[-1][0] + tau_)
        pk, tr, auc = ss_values(md_dose, tau_, md_t, k, V, t12)
        return {
            "ld": ld_dose, "ld_kg": ld_dose / w if ld_dose else 0, "ld_tinf": ld_t if ld_dose else 0,
            "md": md_dose, "md_kg": md_dose / w, "md_tinf": md_t, "tau": tau_,
            "peak": pk, "trough": tr, "auc_ss": auc,
            "auc0_24": window_auc(iv, tau_, 0), "auc24_48": window_auc(iv, tau_, 1),
            "rate_ld": (ld_dose / ld_t) if ld_dose else 0, "rate_md": md_dose / md_t,
            "status": {"peak": status(pk, None, 50), "trough": status(tr, 5, 15), "auc": status(auc, 400, 600)},
            "curve": curve(doses, k, V, t12, hours),
        }

    res = {
        "patient": {"ibw": ibw, "pct_ibw": pct, "condition": cond, "dosing_weight": wt, "crcl": crcl, "vd": V,
                    "cl": CL, "k": k, "t12": t12, "tau_text": tau_text,
                    "model": "Bolus" if is_bolus(t_md, t12) else "Truyền ngắn (short infusion)"},
        "with_ld": regimen(ld, t_ld, md, t_md, tau),
        "without_ld": regimen(0, 0, md, t_md, tau),
        "thresholds": {"peak": thr_pk, "trough": thr_tr}, "hours": hours,
    }
    mld = _f(p.get("man_ld"), "Liều nạp thủ công", 0, 5000, default=0)
    mmd = _f(p.get("man_md"), "Liều duy trì thủ công", 0, 5000, default=0)
    mtau = _f(p.get("man_tau"), "Khoảng cách liều thủ công", 1, 72, default=12)
    if mmd > 0:
        res["manual"] = regimen(mld, infusion_time(mld) if mld else 0, mmd, infusion_time(mmd), mtau)
    warn = []
    for key, name in (("with_ld", "có liều nạp"), ("without_ld", "không liều nạp")):
        r = res[key]
        if r["rate_md"] > 1000:
            warn.append(f"Phác đồ {name}: tốc độ truyền duy trì {r['rate_md']:.0f} mg/h > 1000 mg/h.")
    if ld >= 3000:
        warn.append("Liều nạp đã bị giới hạn ở 3000 mg.")
    if crcl > 130:
        warn.append("CrCl rất cao (>130 mL/phút): công thức dân số có thể ước lượng kém - nên đo nồng độ sớm.")
    res["warnings"] = warn
    return res


# ----------------------------------------------------------------------------- Vancomycin: chinh lieu theo 2 nong do
def vanco_two(p):
    steady = str(p.get("steady", "Y")).upper().startswith("Y")
    nd = int(_f(p.get("ndose"), "Số liều đã dùng", 1, 2, default=1)) if not steady else 1
    d1 = _f(p.get("dose1"), "Liều (mg)", 1, 10000)
    t1i = _f(p.get("tinf1"), "Thời gian truyền (h)", 0.1, 24)
    tau = _f(p.get("tau"), "Khoảng cách liều (h)", 1, 96)
    wt = _f(p.get("weight"), "Cân nặng (kg)", 10, 300)
    s1 = _f(p.get("t1"), "Thời điểm lấy mẫu 1 (h)", 0, 200)
    s2 = _f(p.get("t2"), "Thời điểm lấy mẫu 2 (h)", 0, 200)
    c1 = _f(p.get("c1"), "Nồng độ 1 (mg/L)", 0.1, 500)
    c2 = _f(p.get("c2"), "Nồng độ 2 (mg/L)", 0.05, 500)
    thr_pk = _f(p.get("thr_peak"), "Ngưỡng đỉnh", 1, 200, default=40)
    thr_tr = _f(p.get("thr_trough"), "Ngưỡng đáy", 0.1, 100, default=15)
    if s2 <= s1:
        raise ValueError("Mẫu 2 phải lấy sau mẫu 1.")
    if c2 >= c1:
        raise ValueError("Nồng độ mẫu 2 phải thấp hơn mẫu 1 (cùng trong pha thải trừ) để tính hằng số thải trừ.")
    k = math.log(c1 / c2) / (s2 - s1)
    t12 = LN2 / k

    # lich su lieu (thoi gian tinh tu luc bat dau truyen cua lieu 'goc'); plan = lich du kien tiep theo
    if steady or nd == 1:
        last_ts, last_dose, last_tinf = 0.0, d1, t1i
        hist = [(0.0, d1, t1i)]
        plan = [(j * tau, d1, t1i) for j in range(int(96 // tau) + 2)]
    else:
        d2 = _f(p.get("dose2"), "Liều thứ 2 (mg)", 1, 10000)
        t2i = _f(p.get("tinf2"), "Thời gian truyền liều 2 (h)", 0.1, 24)
        last_ts, last_dose, last_tinf = tau, d2, t2i
        hist = [(0.0, d1, t1i), (tau, d2, t2i)]
        plan = [(0.0, d1, t1i)] + [(j * tau, d2, t2i) for j in range(1, int(96 // tau) + 2)]
    base = [(-j * tau, d1, t1i) for j in range(n_back(k, tau), 0, -1)] if steady else []
    s_abs1, s_abs2 = last_ts + last_tinf + s1, last_ts + last_tinf + s2
    bolus = is_bolus(last_tinf, t12)
    # V tu nong do thu 2 (nong do ty le nghich voi V)
    unit = conc(s_abs2, base + hist, k, 1.0, bolus, t12=t12)
    V = unit / c2
    CL = k * V
    # kiem tra lai: nong do du doan tai mau 1
    pred1 = conc(s_abs1, base + hist, k, V, bolus, t12=t12)
    pk, tr, auc = ss_values(last_dose, tau, last_tinf, k, V, t12)
    cur_doses = base + plan if steady else plan
    horizon = max(48.0, s_abs2 + tau)
    cur_doses = [d for d in cur_doses if d[0] <= horizon + 1e-9]
    cur_curve = curve(cur_doses, k, V, t12, horizon)
    iv_cur = intervals([d for d in cur_doses if d[0] >= 0], k, V, t12, horizon + tau) if not steady else None
    cur = {
        "dose": last_dose, "tinf": last_tinf, "tau": tau, "dose_kg": last_dose / wt,
        "peak": pk, "trough": tr, "auc24": auc,
        "auc0_24": window_auc(iv_cur, tau, 0) if iv_cur else None,
        "auc24_48": window_auc(iv_cur, tau, 1) if iv_cur else None,
        "rate": last_dose / last_tinf,
        "status": {"peak": status(pk, None, 50), "trough": status(tr, 5, 20), "auc": status(auc, 400, 600)},
        "curve": cur_curve,
    }
    res = {
        "pk": {"k": k, "t12": t12, "cl": CL, "cl_ml": CL / 0.06, "vd": V, "vd_kg": V / wt,
               "model": "Bolus" if bolus else "Truyền ngắn (short infusion)", "pred_c1": pred1,
               "state": "Đã đạt trạng thái ổn định" if steady else f"Chưa ổn định ({nd} liều đã dùng)"},
        "current": cur,
        "samples": [[s_abs1, c1], [s_abs2, c2]],
        "thresholds": {"peak": thr_pk, "trough": thr_tr}, "hours": horizon,
        "warnings": [],
    }
    # lieu dieu chinh (thu cong)
    mdose = _f(p.get("man_dose"), "Liều điều chỉnh", 0, 10000, default=0)
    if mdose > 0:
        mtinf = _f(p.get("man_tinf"), "TG truyền điều chỉnh", 0.1, 24, default=last_tinf)
        mtau = _f(p.get("man_tau"), "Khoảng cách liều điều chỉnh", 1, 96, default=tau)
        raw_gap = p.get("man_gap")
        nxt = last_ts + math.ceil((s_abs2 - last_ts + 1e-9) / tau) * tau  # lieu ke tiep theo lich cu sau mau 2
        held = raw_gap not in (None, "")
        if held:
            # nguoi dung nhap: lieu moi bat dau sau X gio ke tu lieu cuoi cung (lieu lay dinh/day), khong them lieu cu nao
            gap = _f(raw_gap, "Thời gian từ liều cuối đến liều mới", 0, 336)
            ts0 = last_ts + gap
            if ts0 < s_abs2 - 1e-9:
                raise ValueError(f"Liều mới phải bắt đầu sau thời điểm lấy mẫu 2: tối thiểu {s_abs2 - last_ts:.1f} giờ sau liều cuối "
                                 f"(đang nhập {gap:g} giờ).")
            hold_from = last_ts + last_tinf
            cont = []
        else:
            gap, ts0, hold_from = 0.0, nxt, nxt
            cont = [d for d in plan if last_ts < d[0] < nxt - 1e-9]
        past = [d for d in (base + hist) if d[0] < ts0]
        newd = [(ts0 + j * mtau, mdose, mtinf) for j in range(0, int(120 // mtau) + 2)]
        allr = past + cont + newd
        hz2 = ts0 + min(4 * mtau, 96)
        allr = [d for d in allr if d[0] <= hz2 + 1e-9]
        pk2, tr2, auc2 = ss_values(mdose, mtau, mtinf, k, V, t12)
        # khoang tinh tren toan bo lich su (co phan thuoc con lai), chi lay tu liều dieu chinh dau tien
        iv2 = [r for r in intervals(sorted(allr), k, V, t12, hz2 + mtau) if r["ts"] >= ts0 - 1e-9]
        res["revised"] = {
            "dose": mdose, "tinf": mtinf, "tau": mtau, "gap": gap, "held": held, "start": ts0, "hold_from": hold_from, "dose_kg": mdose / wt,
            "peak": pk2, "trough": tr2, "auc24": auc2,
            "auc0_24": window_auc(iv2, mtau, 0), "auc24_48": window_auc(iv2, mtau, 1),
            "rate": mdose / mtinf,
            "first_peak": iv2[0]["peak"] if iv2 else None, "first_trough": iv2[0]["trough"] if iv2 else None,
            "status": {"peak": status(pk2, None, 50), "trough": status(tr2, 5, 20), "auc": status(auc2, 400, 600)},
            "curve": curve(sorted(allr), k, V, t12, hz2),
            "hours": hz2,
        }
        if mdose / mtinf > 1000:
            res["warnings"].append(f"Liều điều chỉnh: tốc độ truyền {mdose / mtinf:.0f} mg/h > 1000 mg/h.")
    if last_dose / last_tinf > 1000:
        res["warnings"].append(f"Liều hiện tại: tốc độ truyền {last_dose / last_tinf:.0f} mg/h > 1000 mg/h.")
    if s2 > tau + last_tinf and steady:
        res["warnings"].append("Mẫu 2 lấy sau liều kế tiếp theo lịch - kiểm tra lại thời điểm lấy mẫu.")
    if abs(pred1 - c1) / c1 > 0.10:
        res["warnings"].append(f"Nồng độ mẫu 1 mô hình dự đoán {pred1:.1f} mg/L lệch >10% so với đo {c1:g} mg/L: "
                               "kiểm tra thời điểm lấy mẫu / ghi chép liều.")
    return res


# ----------------------------------------------------------------------------- Aminoglycoside
AMG_DOSES = {"gentamicin": [80, 120, 240, 320], "amikacin": [250, 500, 750, 1000]}
AMG_TAUS = [8, 12, 24, 48]
AMG_DEFAULT = {"gentamicin": {"cmax": 20, "cmin": 1, "mic": 1}, "amikacin": {"cmax": 60, "cmin": 2, "mic": 2}}


def _amg_curve(doses, k, V, t_end, dt=0.1):
    """Duong cong truyen deu (zero-order) cong don."""
    pts = []
    n = int(round(t_end / dt))
    tl = sorted({round(i * dt, 6) for i in range(n + 1)} | {round(d[0] + d[2], 6) for d in doses if 0 <= d[0] + d[2] <= t_end})
    for t in tl:
        pts.append([round(t, 3), round(conc(t, doses, k, V, False), 4)])
    return pts


def _amg_ss_doses(D, tau, tinf, t_end, ke):
    return [(-j * tau, D, tinf) for j in range(n_back(ke, tau), 0, -1)] + [(j * tau, D, tinf) for j in range(0, int(t_end // tau) + 1)]


def _amg_peak_trough(D, tau, tinf, ke, V):
    if not 0 < tinf <= tau:
        raise ValueError('Thời gian truyền phải lớn hơn 0 và không vượt khoảng cách liều.')
    cmax = (D / tinf) / (V * ke) * (1 - math.exp(-ke * tinf)) / (1 - math.exp(-ke * tau))
    return cmax, cmax * math.exp(-ke * (tau - tinf))


def _tmic(cmax, mic, ke):
    return (math.log(cmax) - math.log(mic)) / ke if cmax > mic else 0.0


def amg_start(p):
    age = _f(p.get("age"), "Tuổi", 1, 120)
    abw = _f(p.get("weight"), "Cân nặng thực", 10, 300)
    h = _f(p.get("height"), "Chiều cao", 100, 230)
    scr = _f(p.get("scr"), "Creatinin máu (µmol/L)", 10, 2000)
    female = str(p.get("sex", "0")) in ("1", "F", "f", "Nu", "Nữ")
    D = _f(p.get("dose"), "Liều thực tế đã dùng", 1, 5000)
    tau_a = _f(p.get("tau"), "Khoảng cách liều thực tế", 1, 96)
    tinf = _f(p.get("tinf"), "Thời gian truyền", 0.1, 6, default=0.5)
    hours = _f(p.get("hours"), "Số giờ vẽ", 12, 168, default=72)

    bmi = abw / (h / 100) ** 2
    ibw = (45.5 if female else 50) + 0.9 * (h - 152)
    adw = ibw + 0.4 * (abw - ibw)
    ratio = abw / ibw
    wsel = adw if ratio > 1.2 else abw if ratio >= 0.9 else ibw if ratio > 0.75 else abw * 1.13
    vd = 0.26 * wsel if bmi < 30 else 0.26 * adw
    crcl = (140 - age) * wsel * (1.04 if female else 1.23) / scr
    cl = crcl * 60 / 1000
    ke = cl / vd
    t12 = 0.693 / ke
    out = {"patient": {"bmi": bmi, "ibw": ibw, "adw": adw, "weight_used": wsel, "vd": vd, "crcl": crcl, "cl": cl,
                       "ke": ke, "t12": t12}, "drugs": {}, "hours": hours}
    # Cmax/Cmin du doan voi lieu thuc te
    cmax_a, cmin_a = _amg_peak_trough(D, tau_a, tinf, ke, vd)
    out["actual"] = {"dose": D, "tau": tau_a, "tinf": tinf, "cmax": cmax_a, "cmin": cmin_a,
                     "curve": _amg_curve(_amg_ss_doses(D, tau_a, tinf, hours, ke), ke, vd, hours)}
    for name in ("gentamicin", "amikacin"):
        d0 = AMG_DEFAULT[name]
        cmax_t = _f(p.get(f"{name}_cmax"), f"Cmax mục tiêu {name}", 0.5, 500, default=d0["cmax"])
        cmin_t = _f(p.get(f"{name}_cmin"), f"Cmin mục tiêu {name}", 0.01, 100, default=d0["cmin"])
        mic = _f(p.get(f"{name}_mic"), f"MIC {name}", 0.01, 64, default=d0["mic"])
        if cmin_t >= cmax_t:
            raise ValueError(f"{name}: Cmin mục tiêu phải nhỏ hơn Cmax mục tiêu.")
        tau_est = tinf + (math.log(cmax_t) - math.log(cmin_t)) / ke
        # lam tron khoang cach liều: |tau/F - 1| nho nhat
        tau_r = min(AMG_TAUS, key=lambda F: abs(tau_est / F - 1))
        dose_est = cmax_t * vd * ke * tinf * (1 - math.exp(-ke * tau_r)) / (1 - math.exp(-ke * tinf))
        dose_r = min(AMG_DOSES[name], key=lambda c: abs(dose_est / c - 1))
        cmax_r, cmin_r = _amg_peak_trough(dose_r, tau_r, tinf, ke, vd)
        auc24 = dose_r / cl * 24 / tau_r
        tm = _tmic(cmax_r, mic, ke)
        out["drugs"][name] = {
            "cmax_t": cmax_t, "cmin_t": cmin_t, "mic": mic, "tau_est": tau_est, "tau": tau_r, "dose_est": dose_est,
            "dose": dose_r, "cmax": cmax_r, "cmin": cmin_r, "auc24": auc24, "auc_mic": auc24 / mic,
            "cmax_mic": cmax_r / mic, "tmic": tm, "dfp": tau_r - tinf - tm,
            "curve": _amg_curve(_amg_ss_doses(dose_r, tau_r, tinf, hours, ke), ke, vd, hours),
        }
    out["warnings"] = []
    if crcl < 30:
        out["warnings"].append("CrCl < 30 mL/phút: thải trừ aminoglycosid giảm nhiều - nên kiểm tra nồng độ sớm.")
    return out


def amg_two(p):
    mode = "once" if str(p.get("mode", "once")) == "once" else "trad"
    D = _f(p.get("dose"), "Liều thực tế (mg)", 1, 5000)
    tau = _f(p.get("tau"), "Khoảng cách liều thực tế (h)", 1, 96)
    tinf = _f(p.get("tinf"), "Thời gian truyền (h)", 0.1, 6, default=0.5)
    t1 = _f(p.get("t1"), "Thời điểm lấy mẫu 1 (h, từ lúc bắt đầu truyền)", 0, 200)
    t2 = _f(p.get("t2"), "Thời điểm lấy mẫu 2 (h, từ lúc bắt đầu truyền)", 0, 200)
    c1 = _f(p.get("c1"), "Nồng độ 1 (mg/L)", 0.05, 500)
    c2 = _f(p.get("c2"), "Nồng độ 2 (mg/L)", 0.01, 500)
    mic_g = _f(p.get("mic_gentamicin"), "MIC gentamicin", 0.01, 64, default=1)
    mic_a = _f(p.get("mic_amikacin"), "MIC amikacin", 0.01, 64, default=2)
    nd = _f(p.get("new_dose"), "Liều mới (mg)", 1, 5000, default=D)
    ntau = _f(p.get("new_tau"), "Khoảng cách liều mới (h)", 1, 96, default=tau)
    ntinf = _f(p.get("new_tinf"), "Thời gian truyền mới (h)", 0.1, 6, default=tinf)
    if t2 <= t1:
        raise ValueError("Mẫu 2 phải lấy sau mẫu 1.")
    if c2 >= c1:
        raise ValueError("Nồng độ mẫu 2 phải thấp hơn mẫu 1.")
    if t1 < tinf:
        raise ValueError("Mẫu 1 phải lấy sau khi kết thúc truyền (thời điểm mẫu 1 ≥ thời gian truyền).")
    ke = (math.log(c1) - math.log(c2)) / (t2 - t1)
    t12 = 0.693 / ke
    cmax = c1 * math.exp(ke * (t1 - tinf))
    cmin = cmax * math.exp(-ke * (tau - tinf))
    if mode == "once":
        vd = D * (1 - math.exp(-ke * tinf)) / (tinf * cmax * ke)
    else:
        vd = D * (1 - math.exp(-ke * tinf)) / (tinf * ke * cmax * (1 - math.exp(-ke * tau)))
    cl = vd * ke
    res = {"mode": mode, "pk": {"ke": ke, "t12": t12, "cmax": cmax, "cmin": cmin, "vd": vd, "cl": cl},
           "samples": [[t1, c1], [t2, c2]], "mics": {"gentamicin": mic_g, "amikacin": mic_a}, "warnings": []}
    # hien tai
    if mode == "once":  # do tren lieu dau tien
        hz = max(tau * 2, t2 + 4)
        cur = _amg_curve([(j * tau, D, tinf) for j in range(0, int(hz // tau) + 1)], ke, vd, hz)
        tm = {n: _tmic(cmax, m, ke) for n, m in (("gentamicin", mic_g), ("amikacin", mic_a))}
        res["current"] = {"dose": D, "tau": tau, "tinf": tinf, "cmax": cmax, "cmin": cmin, "curve": cur, "hours": hz,
                          "tmic": tm, "dfp": {n: tau - tinf - v for n, v in tm.items()}}
    else:
        hz = tau * 3
        res["current"] = {"dose": D, "tau": tau, "tinf": tinf, "cmax": cmax, "cmin": cmin, "hours": hz,
                          "curve": _amg_curve(_amg_ss_doses(D, tau, tinf, hz, ke), ke, vd, hz)}
    res["current"]["auc24"] = D / cl * 24 / tau
    # lieu moi
    ncmax, ncmin = _amg_peak_trough(nd, ntau, ntinf, ke, vd)
    auc24 = nd / cl * 24 / ntau
    hz2 = ntau * 3
    tm2 = {n: _tmic(ncmax, m, ke) for n, m in (("gentamicin", mic_g), ("amikacin", mic_a))}
    res["new"] = {"dose": nd, "tau": ntau, "tinf": ntinf, "cmax": ncmax, "cmin": ncmin, "auc24": auc24,
                  "auc_mic": {"gentamicin": auc24 / mic_g, "amikacin": auc24 / mic_a},
                  "cmax_mic": {"gentamicin": ncmax / mic_g, "amikacin": ncmax / mic_a},
                  "tmic": tm2, "dfp": {n: ntau - ntinf - v for n, v in tm2.items()}, "hours": hz2,
                  "curve": _amg_curve(_amg_ss_doses(nd, ntau, ntinf, hz2, ke), ke, vd, hz2)}
    if mode == "trad":
        ct = _f(p.get("cmax_t"), "Cmax mục tiêu", 0.5, 500, default=3)
        cn = _f(p.get("cmin_t"), "Cmin mục tiêu", 0.01, 100, default=1)
        if cn >= ct:
            raise ValueError("Cmin mục tiêu phải nhỏ hơn Cmax mục tiêu.")
        tau_e = tinf + math.log(ct / cn) / ke
        dose_e = ct * vd * ke * tinf * (1 - math.exp(-ke * tau_e)) / (1 - math.exp(-ke * tinf))
        res["target"] = {"cmax_t": ct, "cmin_t": cn, "tau_est": tau_e, "dose_est": dose_e}
    if cmax <= 0 or vd <= 0:
        res["warnings"].append("Kết quả bất thường - kiểm tra lại dữ liệu nhập.")
    if t1 < tinf + 0.5 and mode == "once":
        res["warnings"].append("Mẫu 1 nên lấy ≥ 30 phút sau khi kết thúc truyền (pha phân bố).")
    return res


# ----------------------------------------------------------------------------- Flask
def make_blueprint():
    from flask import Blueprint, jsonify, request
    bp = Blueprint("tdm", __name__)

    def run(fn):
        try:
            return jsonify(ok=True, **fn(request.get_json(silent=True) or {}))
        except ValueError as e:
            return jsonify(ok=False, msg=str(e)), 400
        except ZeroDivisionError:
            return jsonify(ok=False, msg="Số liệu nhập gây phép chia cho 0 - kiểm tra lại.")
        except OverflowError:
            return jsonify(ok=False, msg="Số liệu nhập quá lớn/nhỏ bất thường - kiểm tra lại.")
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            return jsonify(ok=False, msg=f"Lỗi tính toán: {e}")

    @bp.post("/api/tdm/vanco/empiric")
    def v_emp():
        return run(vanco_empiric)

    @bp.post("/api/tdm/vanco/two")
    def v_two():
        return run(vanco_two)

    @bp.post("/api/tdm/amg/start")
    def a_start():
        return run(amg_start)

    @bp.post("/api/tdm/amg/two")
    def a_two():
        return run(amg_two)

    return bp

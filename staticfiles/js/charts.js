/* ==========================================================================
   Dependency-free SVG line charts for the analytics dashboard.
   Data arrives in a data-chart attribute; no chart library, no CDN — which
   also keeps the Content-Security-Policy strict.
   ========================================================================== */
(function () {
    "use strict";

    function draw(canvas, series, colour) {
        if (!series || series.length === 0) return;

        const width = canvas.clientWidth || 480;
        const height = canvas.clientHeight || 200;
        const padding = { top: 12, right: 8, bottom: 22, left: 36 };

        const values = series.map((p) => p.value);
        const max = Math.max(...values, 1);
        const min = Math.min(...values, 0);
        const range = max - min || 1;

        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const step = series.length > 1 ? plotWidth / (series.length - 1) : 0;

        const points = series.map((point, index) => {
            const x = padding.left + index * step;
            const y = padding.top + plotHeight - ((point.value - min) / range) * plotHeight;
            return [x, y];
        });

        const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        const area = `${line} L${points[points.length - 1][0].toFixed(1)},${padding.top + plotHeight} `
                   + `L${points[0][0].toFixed(1)},${padding.top + plotHeight} Z`;

        const gridLines = [0, 0.5, 1].map((fraction) => {
            const y = padding.top + plotHeight * fraction;
            const label = Math.round(max - range * fraction);
            return `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}"
                          stroke="currentColor" stroke-opacity=".12"/>
                    <text x="${padding.left - 6}" y="${y + 4}" text-anchor="end"
                          font-size="10" fill="currentColor" fill-opacity=".55">${label}</text>`;
        }).join("");

        const first = series[0].date.slice(5);
        const last = series[series.length - 1].date.slice(5);
        const gradientId = "grad-" + Math.random().toString(36).slice(2, 8);

        canvas.innerHTML = `
            <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}"
                 role="img" aria-label="Trend chart">
                <defs>
                    <linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="${colour}" stop-opacity=".28"/>
                        <stop offset="100%" stop-color="${colour}" stop-opacity="0"/>
                    </linearGradient>
                </defs>
                ${gridLines}
                <path d="${area}" fill="url(#${gradientId})"/>
                <path d="${line}" fill="none" stroke="${colour}" stroke-width="2"
                      stroke-linejoin="round" stroke-linecap="round"/>
                <text x="${padding.left}" y="${height - 6}" font-size="10"
                      fill="currentColor" fill-opacity=".55">${first}</text>
                <text x="${width - padding.right}" y="${height - 6}" font-size="10"
                      text-anchor="end" fill="currentColor" fill-opacity=".55">${last}</text>
            </svg>`;
    }

    const palette = {
        matches: "#7c3aed",
        messages: "#0284c7",
        revenue: "#16a34a",
        likes: "#ec4899",
        default: "#7c3aed",
    };

    // Dashboard: one payload holding several named series.
    const dashboard = document.querySelector("[data-charts]");
    if (dashboard) {
        const charts = JSON.parse(dashboard.dataset.charts || "{}");
        Object.entries(charts).forEach(([name, series]) => {
            const target = document.querySelector(`[data-chart="${name}"]`);
            if (target) draw(target, series, palette[name] || palette.default);
        });
    }

    // Metric detail page: a single series.
    document.querySelectorAll("[data-series]").forEach((node) => {
        draw(node, JSON.parse(node.dataset.series || "[]"), palette.default);
    });
})();

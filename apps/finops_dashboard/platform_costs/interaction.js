// Shared by the Streamlit component and the local preview. No Python rerun on hover.
export function mountCostChart(root, figure, Plotly) {
    const plot = root.querySelector('.platform-cost-interactive-chart');
    const layout = structuredClone(figure.layout);
    const noteIndex = (layout.annotations || []).findIndex(note => note.name === 'currency_scale_note');
    const originalNote = noteIndex < 0 ? '' : layout.annotations[noteIndex].text.replace(/<\/?i>/g, '');
    const themeColor = () => getComputedStyle(plot).color;
    let color = themeColor();
    layout.font = {...layout.font, color, family: getComputedStyle(plot).fontFamily};
    layout.paper_bgcolor = layout.plot_bgcolor = 'rgba(0,0,0,0)';
    for (const key of ['xaxis', 'yaxis', 'yaxis2']) {
        layout[key] = {...layout[key], gridcolor: 'rgba(128,128,128,0.16)', zerolinecolor: 'rgba(128,128,128,0.3)'};
    }
    let alive = true, active = null;
    const originalStyles = new WeakMap();
    function focus(point) {
        if (!alive) return;
        active = point || null;
        const visible = plot.data.map((trace, index) => ({trace,index}))
            .filter(({trace}) => trace.visible !== false && trace.visible !== 'legendonly');
        // Style only SVG points, without a Plotly redraw that would cancel hover.
        // Plotly's bound indices preserve missing points and hidden-legend traces.
        plot.querySelectorAll('.barlayer .trace').forEach((group, order) => {
            const curve = group.__data__?.[0]?.trace?.index ?? visible[order]?.index;
            group.querySelectorAll('.point').forEach((element, order) => {
                if (!originalStyles.has(element)) originalStyles.set(element, element.style.opacity);
                const index = element.__data__?.i ?? order;
                if (point) element.style.opacity = curve === point.curveNumber && index === point.pointNumber ? '1' : '0.22';
                else element.style.opacity = originalStyles.get(element);
            });
        });
    }
    function leave() { focus(null); }
    function wrapNote() {
        if (!alive || noteIndex < 0) return;
        const width = Math.max(120, plot.clientWidth - layout.margin.l - layout.margin.r);
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        context.font = `italic 12px ${getComputedStyle(plot).fontFamily}`;
        const lines = [''];
        for (const word of originalNote.split(' ')) {
            const index = lines.length - 1;
            const candidate = lines[index] ? `${lines[index]} ${word}` : word;
            if (lines[index] && context.measureText(candidate).width > width) lines.push(word);
            else lines[index] = candidate;
        }
        // The note is constant authored text, not billing source content.
        const text = `<i>${lines.join('<br>')}</i>`;
        if (plot.layout?.annotations?.[noteIndex]?.text !== text)
            Plotly.relayout(plot, {[`annotations[${noteIndex}].text`]: text});
    }
    Plotly.newPlot(plot, structuredClone(figure.data), layout,
        {responsive: true, displaylogo: false}).then(() => {
        if (!alive) { Plotly.purge(plot); return; }
        plot.on('plotly_hover', event => focus(event.points?.[0]));
        plot.on('plotly_unhover', leave);
        plot.on('plotly_legendclick', () => focus(null));
        plot.on('plotly_afterplot', () => { if (active) focus(active); });
        wrapNote();
    });
    plot.addEventListener('pointerleave', leave);
    const resize = new ResizeObserver(() => { if (alive && plot.layout) { Plotly.Plots.resize(plot); wrapNote(); } });
    resize.observe(plot);
    // Theme changes can occur without a Python rerun.
    const theme = new MutationObserver(() => {
        const next = themeColor();
        if (alive && plot.layout && next !== color) { color = next; Plotly.relayout(plot, {'font.color': color}); }
    });
    theme.observe(document.documentElement, {attributes:true, subtree:true, attributeFilter:['class', 'style']});
    return () => {
        alive = false; resize.disconnect(); theme.disconnect();
        plot.removeEventListener('pointerleave', leave);
        Plotly.purge(plot);
    };
}

export default function(component) {
    return mountCostChart(component.parentElement, component.data.figure, CostPlotly);
}

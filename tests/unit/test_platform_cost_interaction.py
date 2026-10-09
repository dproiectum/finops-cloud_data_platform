"""Browser-only hover logic and Streamlit integration, without live billing access."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/finops_dashboard'))
from platform_costs.interactive_chart import render_cost_chart, SCRIPT


class PlatformCostInteractionTests(unittest.TestCase):
    def test_component_passes_structured_figure_not_interpolated_source_html(self):
        figure = Mock()
        figure.to_json.return_value = json.dumps({'data': [{'name': '<script>untrusted</script>'}], 'layout': {}})
        mount = Mock()
        with patch('platform_costs.interactive_chart.chart_component', return_value=mount):
            render_cost_chart(figure)
        self.assertEqual(mount.call_args.kwargs['data']['figure']['data'][0]['name'], '<script>untrusted</script>')
        self.assertEqual(mount.call_args.kwargs['height'], 510)
        self.assertEqual(mount.call_args.kwargs['key'], 'platform_cost_hover_chart')

    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute the frontend interaction test')
    def test_hover_fades_other_points_restores_and_cleans_up(self):
        harness = r'''
import assert from 'node:assert/strict';
const events = {}, listeners = {};
let purges = 0, disconnects = 0;
const groups = [0,1].map(curve => ({__data__:[{trace:{index:curve}}],
    points:[0,1,2].map(i => ({__data__:{i},style:{opacity:''}})),
    querySelectorAll(){return this.points;}}));
const plot = {clientWidth:900,
    querySelectorAll:()=>groups,
    on:(name, callback)=>events[name]=callback,
    addEventListener:(name, callback)=>listeners[name]=callback,
    removeEventListener:name=>delete listeners[name]};
globalThis.getComputedStyle = () => ({color:'rgb(20,20,20)', fontFamily:'sans-serif'});
globalThis.document = {documentElement:{}, createElement:()=>({getContext:()=>({measureText:s=>({width:s.length*6})})})};
globalThis.ResizeObserver = globalThis.MutationObserver = class {
    constructor(callback) { this.callback=callback; }
    observe() {} disconnect() { disconnects++; }
};
const Plotly = {
    newPlot:(_plot, data, layout)=>{plot.data=data; plot.layout=layout; return Promise.resolve();},
    restyle:()=>{throw new Error('Hover must not redraw the chart');},
    relayout:()=>Promise.resolve(), Plots:{resize:()=>{}}, purge:()=>purges++
};
const figure = {data:[{x:['a','b','c'],y:[1,null,2],marker:{color:'#4285F4'}},
                     {x:['a','b','c'],y:[3,4,null],marker:{color:'#FF543D'}}],
                layout:{margin:{l:75,r:95},annotations:[]}};
const original = JSON.stringify(figure);
const cleanup = mountCostChart({querySelector:()=>plot},figure,Plotly);
const settle = async()=>{await Promise.resolve(); await Promise.resolve(); await Promise.resolve();};
await settle();
events.plotly_hover({points:[{curveNumber:1,pointNumber:0}]});
await settle();
const opacities = () => groups.map(g=>g.points.map(p=>p.style.opacity));
assert.deepEqual(opacities(),[['0.22','0.22','0.22'],['1','0.22','0.22']]);
events.plotly_afterplot(); await settle();
assert.deepEqual(opacities(),[['0.22','0.22','0.22'],['1','0.22','0.22']]);
events.plotly_hover({points:[{curveNumber:0,pointNumber:2}]});
await settle();
assert.deepEqual(opacities(),[['0.22','0.22','1'],['0.22','0.22','0.22']]);
events.plotly_unhover(); await settle();
assert.deepEqual(opacities(),[['','',''],['','','']]);
events.plotly_hover({points:[{curveNumber:1,pointNumber:1}]});
listeners.pointerleave(); await settle();
assert.deepEqual(opacities(),[['','',''],['','','']]);
groups.shift(); // Hidden GCP trace: Databricks must keep its original curve index.
events.plotly_hover({points:[{curveNumber:1,pointNumber:1}]}); await settle();
assert.deepEqual(opacities(),[['0.22','1','0.22']]);
assert.equal(JSON.stringify(figure),original);
cleanup(); assert.equal(purges,1); assert.equal(disconnects,2);
assert.equal(Object.keys(listeners).length,0);
console.log('Hover focus, redraw stability, restoration and cleanup passed');
'''
        result = subprocess.run([shutil.which('node'), '--input-type=module', '--eval', SCRIPT.read_text() + harness],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('passed', result.stdout)

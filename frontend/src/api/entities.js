import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'}),recompute:id=>api('/jobs/'+id+'/recompute',{method:'POST'}),impact:id=>api('/jobs/'+id+'/impact')};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const retractions={list:()=>api('/retractions'),impact:()=>api('/retractions/impact'),create:data=>api('/retractions',{method:'POST',body:JSON.stringify(data)})};

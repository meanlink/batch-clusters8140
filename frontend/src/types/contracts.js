/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string,retracted_batch_ids:string[]}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,excluded_batch_ids:string[]|null,replaces_job_id:number|null,invalidated_at:number|null,invalid_reason:string}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean,voided_at:number|null,void_reason:string}} ReportSchedule */
/** @typedef {{id:number,batch_id:string,reason:string,actor:string,created_at:number}} Retraction */
export {};

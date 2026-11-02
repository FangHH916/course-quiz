'use strict';
// Only opaque encrypted snapshots enter browser storage. API keys never enter this module.
window.ShizhiBackup={
  async database(){
    return new Promise((resolve,reject)=>{
      const request=indexedDB.open('shizhi-encrypted-backups',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('snapshots');
      request.onsuccess=()=>resolve(request.result);
      request.onerror=()=>reject(request.error);
    });
  },
  async get(key){
    const db=await this.database();
    try{return await new Promise((resolve,reject)=>{const request=db.transaction('snapshots','readonly').objectStore('snapshots').get(key);request.onsuccess=()=>resolve(request.result||null);request.onerror=()=>reject(request.error);});}
    finally{db.close();}
  },
  async put(key,value){
    const db=await this.database();
    try{await new Promise((resolve,reject)=>{const transaction=db.transaction('snapshots','readwrite');transaction.objectStore('snapshots').put(value,key);transaction.oncomplete=()=>resolve();transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error||new Error('Backup transaction aborted'));});}
    finally{db.close();}
  },
  async remove(key){
    const db=await this.database();
    try{await new Promise((resolve,reject)=>{const transaction=db.transaction('snapshots','readwrite');transaction.objectStore('snapshots').delete(key);transaction.oncomplete=()=>resolve();transaction.onerror=()=>reject(transaction.error);});}
    finally{db.close();}
  }
};

/* Shared timing validation for the editor and its regression checks. */
(function(root) {
    'use strict';
    function validate(cues, duration) {
        let previous=0;
        for(const c of [...cues].sort((a,b)=>a.start-b.start)) {
            if(!Number.isFinite(c.start)||!Number.isFinite(c.end)||c.start<0||c.end>duration||c.end<=c.start)
                throw Error('A caption must start before it ends and stay inside the video.');
            if(c.start<previous-.001)throw Error('Caption lines cannot overlap.');
            previous=c.end;
            let wordEnd=c.start;
            for(const w of c.words||[]) {
                if(!Number.isFinite(w.start)||!Number.isFinite(w.end)||w.start<wordEnd||w.end>c.end||w.end<=w.start)
                    throw Error('Word timings must run forwards, stay inside the line, and not overlap.');
                wordEnd=w.end;
            }
        }
    }
    if(typeof module!=='undefined'&&module.exports)module.exports={validate};
    else root.CaptionTiming={validate};
})(typeof window==='undefined'?globalThis:window);

"""Structured model proposals, bounded known-target resolution; no execution."""
from difflib import SequenceMatcher
import re

MIN_CONFIDENCE=.90
MIN_TARGET_SCORE=.84


class ClarificationNeeded(ValueError):
    pass


def aliases(target):
    names=[target]
    if target=='Default playlist': names+=['my playlist','my default playlist']
    if target=='Jarvis project': names+=['my Jarvis project','Jarvis in VS Code','VS Code','vscode']
    if target=='Windows Documents': names+=['documents','document folder']
    return names


def compact(text):
    return re.sub(r'[^a-z0-9]','',text.casefold())


def resolve_target(raw,targets):
    if not isinstance(raw,str) or not raw.strip() or len(raw)>80 or re.search(r'[\\/:;`$]|\.\.',raw):
        raise ClarificationNeeded('Please name a supported app or saved resource, rather than a path or command.')
    value=compact(raw)
    ranked=sorted(((max(SequenceMatcher(None,value,compact(alias)).ratio() for alias in aliases(target)),target)
                   for target in targets),reverse=True)
    exact=[target for score,target in ranked if score==1]
    if len(exact)==1: return exact[0]
    if not ranked: raise ClarificationNeeded('That action has no supported targets.')
    if ranked[0][0]<MIN_TARGET_SCORE or (len(ranked)>1 and ranked[0][0]-ranked[1][0]<.12):
        options=[target for score,target in ranked[:2] if score>=.4]
        raise ClarificationNeeded('Did you mean '+ ' or '.join(options)+'?' if options else 'Which supported app or saved resource did you mean?')
    return ranked[0][1]


def mentioned(target,text,targets):
    # Inspect only current typed/transcribed words. No recalled data or paths.
    if re.search(r'[\\/]|\b[a-z]:|\.\.',text,re.I): return False
    words=re.findall(r'[\w]+',text)
    for start in range(len(words)):
        for length in range(1,min(5,len(words)-start+1)):
            try:
                if resolve_target(' '.join(words[start:start+length]),targets)==target: return True
            except ClarificationNeeded: pass
    return False


def normalize_intent(proposal,text,targets,context_target=None):
    if not isinstance(proposal,dict) or set(proposal)!={'action','target','confidence'}:
        raise ClarificationNeeded('Please clarify the action and target.')
    confidence=proposal['confidence']
    if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not MIN_CONFIDENCE<=confidence<=1:
        raise ClarificationNeeded('I’m not certain what action you want. Could you clarify?')
    target=resolve_target(proposal['target'],targets)
    # A validated play/pause receipt identifies Spotify's current media session,
    # not a request to reselect a playlist. Resolve only this unambiguous family
    # reference; explicit playlist requests keep their registered target.
    if proposal['action']=='spotify_playback' and context_target in {'Spotify Play','Spotify Pause'} \
            and re.search(r'\b(?:that|it)\b',text,re.I) and not mentioned(target,text,targets):
        verbs=[verb for verb in ('play','pause') if re.search(r'\b'+verb+r'\b',text,re.I)]
        if len(verbs)==1:
            target='Spotify Play' if verbs[0]=='play' else 'Spotify Pause'
    if proposal['action']=='spotify_playback' and target in {'Spotify Play','Spotify Pause'}:
        verb='play' if target=='Spotify Play' else 'pause'
        named=mentioned('Spotify',text,['Spotify','Chrome'])
        related=context_target in {'Spotify','Spotify Play','Spotify Pause','Default playlist'}
        reference=related and bool(re.search(r'\b(?:that|it)\b',text,re.I))
        if not re.search(r'\b'+verb+r'\b',text,re.I) or not (named or reference):
            raise ClarificationNeeded('Which app should I '+verb+'?')
        return {'action':proposal['action'],'target':target,'confidence':confidence}
    contextual=(context_target==target and bool(re.search(r'\b(?:that|it)\b',text,re.I)))
    if not mentioned(target,text,targets) and not contextual:
        raise ClarificationNeeded('Which supported target should I use for this request?')
    return {'action':proposal['action'],'target':target,'confidence':confidence}

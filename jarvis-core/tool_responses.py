"""Deterministic acknowledgements and evidence-qualified action receipts."""


def action_phrase(action, target):
    name = {'Jarvis project': 'your Jarvis project', 'Default playlist': 'your playlist',
            'Windows Documents': 'your Documents folder'}.get(target, target)
    if action == 'spotify_playback':
        if target not in {'Spotify Play','Spotify Pause'}: return 'put ' + name + ' on'
        return ('pause' if target == 'Spotify Pause' else 'play') + ' Spotify'
    if action == 'inspect_app': return 'take a look at ' + name
    if action == 'focus_app': return 'bring ' + name + ' forward'
    return ('open ' if action == 'open_resource' else 'pull up ') + name


def acknowledgement(action, target):
    return ('Got it, I’ll ' if target == 'Jarvis project' else 'Sure, I’ll ') + action_phrase(action, target) + '.'


def combined_acknowledgement(results):
    phrases = [action_phrase(item['action_type'], item['target']) for item in results]
    joined = phrases[0] if len(phrases) == 1 else ', '.join(phrases[:-1]) + ' and ' + phrases[-1]
    return 'Got it, I’ll ' + joined + '.'


def receipt(result):
    target=result['target']
    status=result['status']
    if status=='denied':
        return 'Okay, I won’t ' + action_phrase(result.get('action_type', 'open_app'), target) + '.'
    ack=acknowledgement(result.get('action_type','open_app'),target)
    if status=='approval_required':
        return ack
    if result.get('action_type') == 'inspect_app':
        observation = result.get('observation', {})
        return 'Inspected ' + target + ' without clicking or typing. ' + str(len(observation.get('controls', []))) + ' control labels returned' + ('; the view is incomplete.' if observation.get('partial') else '.')
    if result.get('action_type') == 'focus_app':
        return target + ' is in the foreground.' if result.get('focused') is True else 'The foreground window could not be confirmed.'
    if result.get('resource_kind')=='playlist':
        if result.get('action_type') == 'spotify_playback':
            return 'Your playlist is playing.' if result.get('playback_confirmed') is True else 'I opened your playlist, but couldn’t confirm playback started.'
        return ack
    if result.get('action_type')=='spotify_playback':
        desired = target == 'Spotify Play'
        if result.get('playing') is desired:
            return 'Spotify is playing.' if desired else 'Spotify is paused.'
        return 'I couldn’t confirm that Spotify ' + ('started playing.' if desired else 'paused.')
    return ack

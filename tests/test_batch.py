from copy import deepcopy
import numpy as np
import pytest
from materialmind.acquisition import AcquisitionWeights, rank_candidates, recommend_batch
from materialmind.learning import fit_model
from test_learning import fixtures
from test_server import client


def test_batch_matches_direct_sequential_recomputation_without_refitting():
    records, labels = fixtures()
    train, cal, pool = records[:50], records[50:70], records[70:]
    model = fit_model(train, cal, {r['id']: labels[r['id']] for r in train + cal}, n_estimators=12)
    before = deepcopy(records)
    weights = AcquisitionWeights(exploration=.2, diversity=.7, cost_exponent=.5)
    actual = recommend_batch(model, pool, train, 10, weights)
    selected, remaining, known = [], list(pool), list(train)
    for row in actual:
        expected = rank_candidates(model, remaining, known, weights)[0]
        assert row['id'] == expected['id']
        assert row['acquisition'] == pytest.approx(expected['acquisition'], abs=1e-12)
        assert row['novelty'] == pytest.approx(expected['novelty'], abs=1e-12)
        selected.append(row['id'])
        picked = next(r for r in remaining if r['id'] == row['id'])
        known.append(picked)
        remaining.remove(picked)
    assert len(selected) == len(set(selected)) == 10
    assert records == before
    assert [r['batch_position'] for r in actual] == list(range(1,11))


def test_diversity_changes_second_choice_from_static_top_two():
    class Model:
        cost_scale = 1.
        def latent(self, rows): return np.array([r['location'] for r in rows])
        def arrays(self, rows, calibrated=True):
            n=len(rows)
            return dict(mean=np.full(n,.1),sigma=np.full(n,.1),width=np.full(n,.2),probability=np.full(n,.5))
    pool=[dict(id=i,location=x,predicted_hull=.1,cost=1.) for i,x in [('a',[0.,0.]),('b',[.001,0.]),('c',[1.,0.])]]
    known=[dict(id='known',location=[-10.,-10.])]
    weights=AcquisitionWeights(exploration=0,diversity=1,cost_exponent=0)
    assert [r['id'] for r in rank_candidates(Model(),pool,known,weights)[:2]] == ['a','b']
    assert [r['id'] for r in recommend_batch(Model(),pool,known,2,weights)] == ['a','c']
    for count in (0,21,True,1.5):
        with pytest.raises(ValueError): recommend_batch(Model(),pool,known,count,weights)
    with pytest.raises(ValueError): recommend_batch(Model(),pool+pool,known,2,weights)
    with pytest.raises(ValueError): recommend_batch(Model(),pool,[pool[0]],2,weights)


def test_api_recommendation_is_label_blind_and_does_not_mutate_session(client):
    before=client.get('/api/session').json()
    result=client.get('/api/recommendations?count=4')
    assert result.status_code == 200
    batch=result.json()['recommendations']
    assert len(batch) == 4
    assert not any({'reference','stable','features','e_above_hull'} & r.keys() for r in batch)
    after=client.get('/api/session').json()
    before.pop('exported_at');after.pop('exported_at')
    assert after == before
    ids=[r['id'] for r in batch]
    assert client.post('/api/reveal',json={'ids':ids}).json()['model_revision'] == 1
    remaining=client.get('/api/recommendations?count=20').json()
    assert remaining['model_revision'] == 1
    assert len(remaining['recommendations']) == 2
    assert not set(ids) & {r['id'] for r in remaining['recommendations']}
    for count in (0,21,'nope'):
        assert client.get(f'/api/recommendations?count={count}').status_code == 422


def test_hidden_pool_label_changes_cannot_change_suggestions(client, monkeypatch):
    import materialmind.server as server
    from fastapi.testclient import TestClient
    expected=client.get('/api/recommendations?count=5').json()
    payload, labels=server.load_dataset()
    altered=dict(labels)
    for row in payload['candidates']:
        if row['split'] in ('test','development'):
            altered[row['id']]=1000.-100*labels[row['id']]
    monkeypatch.setattr(server,'load_dataset',lambda:(deepcopy(payload),altered))
    with TestClient(server.create_app()) as other:
        actual=other.get('/api/recommendations?count=5').json()
        assert actual['recommendations'] == expected['recommendations']
        assert actual['model_revision'] == expected['model_revision']


def test_preview_commit_records_sequential_scores_and_strict_restore(client):
    preview=client.get('/api/recommendations?count=4').json()
    result=client.post('/api/recommendations/reveal',json={'count':4,'snapshot':preview['snapshot']})
    assert result.status_code==200
    value=result.json()
    assert [r['id'] for r in value['results']]==[r['id'] for r in preview['recommendations']]
    assert value['model_revision']==1
    for event,row in zip(value['history'],preview['recommendations']):
        assert event['prediction_at_selection']['acquisition']==pytest.approx(row['acquisition'],abs=1e-12)
        assert event['prediction_at_selection']['novelty']==pytest.approx(row['novelty'],abs=1e-12)
    saved=client.get('/api/session').json()
    assert saved['replay']['batches'][0]['selection_mode']=='sequential'
    assert client.post('/api/recommendations/reveal',json={'count':4,'snapshot':preview['snapshot']}).status_code==409
    client.post('/api/reset')
    restored=client.post('/api/session',json=saved)
    assert restored.status_code==200
    assert restored.json()['history']==value['history']


def test_same_revision_different_choices_invalidate_batch_preview(client):
    client.post('/api/reveal',json={'ids':['test-0']})
    preview=client.get('/api/recommendations?count=3').json()
    client.post('/api/reset')
    client.post('/api/reveal',json={'ids':['test-1']})
    before=client.get('/api/catalog').json()
    assert before['metadata']['model_revision']==preview['model_revision']==1
    response=client.post('/api/recommendations/reveal',json={'count':3,'snapshot':preview['snapshot']})
    assert response.status_code==409
    assert client.get('/api/catalog').json()==before


def test_batch_commit_fit_failure_is_atomic_and_preview_retryable(client,monkeypatch):
    import materialmind.learning as learning
    preview=client.get('/api/recommendations?count=3').json()
    before=client.get('/api/catalog').json()
    fit=learning.fit_model
    def fail(*args,**kwargs): raise RuntimeError('injected fit failure')
    monkeypatch.setattr(learning,'fit_model',fail)
    body={'count':3,'snapshot':preview['snapshot']}
    assert client.post('/api/recommendations/reveal',json=body).status_code==503
    assert client.get('/api/catalog').json()==before
    monkeypatch.setattr(learning,'fit_model',fit)
    assert client.post('/api/recommendations/reveal',json=body).status_code==200


def test_batch_commit_strict_request_and_empty_pool(client):
    preview=client.get('/api/recommendations?count=20').json()
    for count in (True,0,21,1.5):
        assert client.post('/api/recommendations/reveal',json={'count':count,'snapshot':preview['snapshot']}).status_code==422
    assert client.post('/api/recommendations/reveal',json={'count':20,'snapshot':preview['snapshot']}).status_code==200
    empty=client.get('/api/recommendations?count=5').json()
    assert empty['recommendations']==[]
    assert client.post('/api/recommendations/reveal',json={'count':5,'snapshot':empty['snapshot']}).status_code==409


@pytest.mark.parametrize('scale', [.1, 1., 10.])
def test_empty_reference_batch_matches_recomputation_after_each_choice(scale):
    class Model:
        cost_scale = 1.
        def latent(self, rows): return np.array([r['location'] for r in rows])
        def arrays(self, rows, calibrated=True):
            n = len(rows)
            return dict(mean=np.full(n, .1), sigma=np.full(n, .1),
                        width=np.full(n, .2), probability=np.full(n, .5))
    pool = [dict(id=i, location=[scale*x, 0.], predicted_hull=.1, cost=1.)
            for i, x in [('a', 0.), ('b', 2.), ('c', 3.)]]
    original = deepcopy(pool)
    model = Model()
    weights = AcquisitionWeights(exploration=0, diversity=1, cost_exponent=0)
    for count in (1, 2, 3, 20):
        batch = recommend_batch(model, pool, [], count, weights)
        known, remaining = [], list(pool)
        for actual in batch:
            expected = rank_candidates(model, remaining, known, weights)[0]
            assert actual['id'] == expected['id']
            assert actual['novelty'] == pytest.approx(expected['novelty'], abs=1e-12)
            assert actual['acquisition'] == pytest.approx(expected['acquisition'], abs=1e-12)
            picked = next(r for r in remaining if r['id'] == actual['id'])
            known.append(picked)
            remaining.remove(picked)
        assert len(batch) == min(count, len(pool))
        if scale == 1. and count >= 2:
            assert [r['id'] for r in batch[:2]] == ['a', 'c']
            assert batch[1]['novelty'] == 2.
        assert pool == original

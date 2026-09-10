"""Provider catalogs use native CLI metadata and expose no credential fields."""
import json
import subprocess
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
from oncue.providers import parse_models,catalog

class ProviderTests(unittest.TestCase):
    def test_catalog_names_and_free_costs_from_native_metadata(self):
        record={'id':'example','providerID':'opencode','name':'Example model','cost':{'input':0,'output':0},'headers':{'Authorization':'must-not-be-exposed'}}
        parsed=parse_models('opencode/example\n'+json.dumps(record,indent=2))
        self.assertEqual(parsed,[{'id':'opencode/example','name':'Example model','free':True}])
        record['cost']['input']=1
        self.assertFalse(parse_models(json.dumps(record))[0]['free'])
        record.pop('cost')
        self.assertFalse(parse_models(json.dumps(record))[0]['free'])

    def test_failed_model_discovery_is_not_reported_ready(self):
        with TemporaryDirectory() as root,patch('oncue.providers.executable',side_effect=lambda name,data:'/fake/opencode' if name=='opencode' else None),patch('oncue.providers.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','network error')):
            result=catalog(root,{},True)[1]
        self.assertEqual(result['models'],[])
        self.assertIn('Could not list models',result['status'])

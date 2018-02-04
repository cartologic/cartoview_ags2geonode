import requests
import json
import sys
import logging
import geoserver
import uuid
import psycopg2
from shapely.geometry import asShape
# from celery import shared_task, current_task
# from django.db import connections
from django.conf import settings
from geonode import GeoNodeException
from geoserver.catalog import FailedRequestError, Catalog
from geonode.geoserver.helpers import gs_catalog, get_store, ogc_server_settings, get_sld_for, set_attributes
from geonode.layers.models import Layer
from decimal import Decimal
from django.utils.translation import ugettext as _
from django.contrib.auth import get_user_model
from .models import Task

#celery -A cartoview worker -l info -c 10 --app=cartoview.celeryapp:app
logger = logging.getLogger(__name__)

# connection = connections["datastore"]

reload(sys)
sys.setdefaultencoding('utf-8')

types_map = {
    "esriFieldTypeInteger": "{name} integer",
    "esriFieldTypeSmallInteger": "{name} integer",
    "esriFieldTypeString": "{name} character varying({length})",
    "esriFieldTypeDouble": "{name} double precision",
}
geometry_types_map = {
    "esriGeometryPoint": "Point",
    "esriGeometryPolygon": "Polygon",
    "esriGeometryPolyline": "LineString"
}
neglect_fields = ["SHAPE_Length", "SHAPE_Area"]

def get_wkt(geometry):
    if "rings" in geometry:
        shape = asShape({"type": "Polygon","coordinates": geometry["rings"]})
    elif "paths" in geometry:
        paths = geometry["paths"] if len(geometry["paths"]) > 1 else geometry["paths"][0]
        shape = asShape({'type': 'LineString', 'coordinates': paths})
    else:
        shape = asShape({'type': 'Point', 'coordinates': [geometry["x"], geometry["y"]]})
    return shape.wkt



def get_srid(layer_info):
    try:
        sr = layer_info["extent"]["spatialReference"]
        if "latestWkid" in sr:
            return sr["latestWkid"]
        elif sr["wkid"] == 102100:
            return 3857
        return sr["wkid"]
    except:
        # consider WGS84 if cannot get srid
        return 4326


def request_json(url, params=None, method="POST"):
    params = params or dict(f="json")
    req = requests.request(method, url, data=params)
    return req.json()


def create_table(name, layer_info, srid, connection):
    cursor = connection.cursor()
    try:
        fields_def = []
        for f in layer_info["fields"]:
            if f["name"] not in neglect_fields and f["type"] in types_map:
                fields_def.append(types_map[f["type"]].format(**f).lower())
        table = dict(name=name,
                     fields = ",".join(fields_def) ,
                     geometry_type = geometry_types_map[layer_info["geometryType"]],
                     srid=srid)

        sql = "create table {name}(id serial primary key, the_geom geometry({geometry_type},{srid}),{fields});"
        cursor.execute(sql.format(**table))
        cursor.execute("CREATE INDEX spatial_{0}_the_geom ON {0} USING gist(the_geom);".format(name))
    finally:
        cursor.close()
        connection.commit()


def update_status(task, status, **kwargs):
    print status
    task.status = status
    task.message = json.dumps(kwargs)
    task.save()

    # current_task.update_state(state='PROGRESS', meta=kwargs)

def load_features(url, params,layer_info, table_name, features_count, loaded_features, srid, task, connection):
    data = request_json(url, params)
    for feature in data["features"]:
        cursor = connection.cursor()
        try:
            fields_data = []
            fields_def = ["the_geom"]
            for f in layer_info["fields"]:
                if f["name"] not in neglect_fields and f["type"] in types_map:
                    if feature["attributes"][f["name"]] is not None:
                        fields_def.append(f["name"].lower())
                        fields_data.append(feature["attributes"][f["name"]])
            values_exp = ",".join(["ST_GeomFromText('%s', %d)" % (get_wkt(feature["geometry"]), srid,)] + ['%s' for index in range(len(fields_data))])
            sql = "insert into %s(%s) values(%s);" % (table_name, ",".join(fields_def), values_exp)
            cursor.execute(sql, fields_data)
        except:
            print "unable to insert feature"
            print json.dumps(feature)
        finally:
            cursor.close()
            connection.commit()
            loaded_features += 1
            update_status(task, "In Progress", features_count=features_count, loaded_features=loaded_features)
    return loaded_features



def create_feature_store(cat, workspace):
    db = ogc_server_settings.datastore_db
    db_engine = 'postgis' if 'postgis' in db['ENGINE'] else db['ENGINE']
    dsname = db['NAME']
    ds_exists = False
    try:
       
        ds= cat.get_store(dsname,settings.DEFAULT_WORKSPACE)
        print(ds)
        ds_exists = True
    except FailedRequestError:
        ds = cat.create_datastore(dsname, workspace=workspace)
 
 
    ds.connection_parameters.update({
        'validate connections': 'true',
        'max connections': '10',
        'min connections': '1',
        'fetch size': '1000',
        'host': db['HOST'],
        'port': db['PORT'] if isinstance(db['PORT'], basestring) else str(db['PORT']) or '5432',
        'database': db['NAME'],
        'user': db['USER'],
        'passwd': db['PASSWORD'],
        'dbtype': db_engine
    })

    if ds_exists:
        ds.save_method = "PUT"

    cat.save(ds)
    return get_store(cat, dsname, workspace=workspace)



def create_geonode_layer(resource, owner):
    name = resource.name
    the_store = resource.store
    workspace = the_store.workspace
    layer, created = Layer.objects.get_or_create(name=name, defaults={
        "workspace": workspace.name,
        "store": the_store.name,
        "storeType": the_store.resource_type,
        "typename": "%s:%s" % (workspace.name.encode('utf-8'), resource.name.encode('utf-8')),
        "title": resource.title or 'No title provided',
        "abstract": resource.abstract or unicode(_('No abstract provided')).encode('utf-8'),
        "owner": owner,
        "uuid": str(uuid.uuid4()),
        "bbox_x0": Decimal(resource.latlon_bbox[0]),
        "bbox_x1": Decimal(resource.latlon_bbox[1]),
        "bbox_y0": Decimal(resource.latlon_bbox[2]),
        "bbox_y1": Decimal(resource.latlon_bbox[3])
    })
    # recalculate the layer statistics
    set_attributes(layer, [], overwrite=True)
    layer.set_default_permissions()


def create_geoserver_layer(name, user, srid,
        overwrite=False,
        title=None,
        abstract=None,
        charset='UTF-8'):

    if "geonode.geoserver" in settings.INSTALLED_APPS:
        _user, _password = ogc_server_settings.credentials
        #

        # Step 2. Check that it is uploading to the same resource type as
        # the existing resource
        print('>>> Step 2. Make sure we are not trying to overwrite a '
                    'existing resource named [%s] with the wrong type', name)
        the_layer_type = "vector"

        # Get a short handle to the gsconfig geoserver catalog
        cat = Catalog(ogc_server_settings.internal_rest, _user, _password)

        workspace = cat.get_workspace(settings. DEFAULT_WORKSPACE)
        # Check if the store exists in geoserver
        try:
            store = get_store(cat, name, workspace=workspace)
            print("-------------------------",workspace)
        except FailedRequestError as e:
            # There is no store, ergo the road is clear
            pass
        else:
            # If we get a store, we do the following:
            resources = store.get_resources()

            # If the store is empty, we just delete it.
            if len(resources) == 0:
                cat.delete(store)
            else:
                # If our resource is already configured in the store it needs
                # to have the right resource type
                for resource in resources:
                    if resource.name == name:
                        msg = 'Name already in use and overwrite is False'
                        assert overwrite, msg
                        existing_type = resource.resource_type
                        if existing_type != the_layer_type:
                            msg = ('Type of uploaded file %s (%s) '
                                   'does not match type of existing '
                                   'resource type '
                                   '%s' % (name, the_layer_type, existing_type))
                            print(msg)
                            raise GeoNodeException(msg)


        print('Creating vector layer: [%s]', name)
        ds = create_feature_store(cat, workspace)
        gs_resource = gs_catalog.publish_featuretype(name, ds, "EPSG:" + str(srid))


        # # Step 7. Create the style and assign it to the created resource
        # # FIXME: Put this in gsconfig.py
        print('>>> Step 7. Creating style for [%s]' % name)
        publishing = cat.get_layer(name)

        try:
            # geonode 2.6.x
            sld = get_sld_for(cat, publishing)
        except:
            # geonode 2.5.x
            sld = get_sld_for(publishing)
        style = None
        if sld is not None:
            try:
                cat.create_style(name, sld)
                style = cat.get_style(name)
            except geoserver.catalog.ConflictingDataError as e:
                msg = ('There was already a style named %s in GeoServer, '
                       'try to use: "%s"' % (name + "_layer", str(e)))
                logger.warn(msg)
                e.args = (msg,)
                try:
                    cat.create_style(name + '_layer', sld)
                    style = cat.get_style(name + "_layer")
                except geoserver.catalog.ConflictingDataError as e:
                    style = cat.get_style('point')
                    msg = ('There was already a style named %s in GeoServer, '
                           'cannot overwrite: "%s"' % (name, str(e)))
                    logger.error(msg)
                    e.args = (msg,)

            # FIXME: Should we use the fully qualified typename?
            publishing.default_style = style
            cat.save(publishing)
        return gs_resource



# @shared_task
def import_layer_task(name, title, url, owner_username, task_id):
    name = name.lower()
    db = ogc_server_settings.datastore_db
    connection = psycopg2.connect(
        host=db['HOST'],
        user=db['USER'],
        password=db['PASSWORD'],
        dbname=db['NAME'])
    task = Task.objects.get(id=task_id)
    owner = get_user_model().objects.get(username=owner_username)
    print "creating table " + name

    update_status(task, "In Progress", msg="Loading layer info")

    try:
        layer_info = request_json(url)
    except:
        update_status(task, "Error", msg="Error: Cannot connect to arcgis server")
        return
    srid = get_srid(layer_info)
    if layer_info["type"] == "Feature Layer":
        try:
            create_table(name, layer_info, srid, connection)
        except:
            update_status(task, "Error", msg="Error: Cannot create database table try to change the name")
            return
        max_record_count = 1000
        #max_record_count = min(1000, layer_info["maxRecordCount"])
        
        query_url = "%s/query" % url
        update_status(task, "In Progress", msg="Loading features count")
        params = dict(f="json", where="1=1", returnCountOnly="true")
        layer_features_count = request_json(query_url, params)

        features_count = layer_features_count["count"]
        update_status(task, "In Progress",features_count=features_count)
        loaded_features = 0
        if features_count > max_record_count:  # request ids first
            print "load features by ids"
            update_status(task, "In Progress", msg="Loading features ids",loaded_features=loaded_features, features_count=features_count)
            params = dict(f="json", where="1=1", returnIdsOnly="true")
            layer_features_ids = request_json(query_url, params)
            update_status(task, "In Progress", msg="Loading features",loaded_features=loaded_features, features_count=features_count)
            while len(layer_features_ids["objectIds"]) > 0:
                ids = layer_features_ids["objectIds"][0: max_record_count - 1]
                del layer_features_ids["objectIds"][0: max_record_count - 1]
                params = dict(f="json", outFields="*", objectIds=",".join([str(i) for i in ids]))
                print "load features from %d to %d" % (ids[0],ids[-1], )
                try:
                    loaded_features = load_features(query_url, params, layer_info, name, features_count, loaded_features, srid, task, connection)
                except:
                    print "cannot load features from %d to %d" % (ids[0],ids[-1], )
        else:  # request all features
            print "load all feature at one"
            update_status(task, "In Progress", msg="Loading features", loaded_features=loaded_features, features_count=features_count)
            params = dict(f="json", where="1=1", outFields="*")
            loaded_features = load_features(query_url, params, layer_info, name, features_count, loaded_features, srid, task, connection)

        layer_resource = create_geoserver_layer(name, owner, srid, title=title)
        print 'added to geoserver'
        create_geonode_layer(layer_resource, owner)
        print 'geonode layer %s:%s' %(layer_resource.workspace.name, layer_resource.name,)
        update_status(task, "Finished", msg="Layer imported successfully", layer="%s:%s" %(layer_resource.workspace.name, layer_resource.name,))
        # return {"msg": "Layer Imported Successfully", "layer": "%s:%s" %(layer_resource.workspace.name, layer_resource.name,)}

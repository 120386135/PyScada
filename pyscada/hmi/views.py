# -*- coding: utf-8 -*-
from pyscada.models import Client
from pyscada.models import Variable
from pyscada.models import RecordedDataFloat
from pyscada.models import RecordedDataInt
from pyscada.models import RecordedDataBoolean
from pyscada.models import RecordedTime
from pyscada.hmi.models import Chart
from pyscada.hmi.models import Page
from pyscada.hmi.models import ControlItem
from pyscada.hmi.models import SlidingPanelMenu
from pyscada.hmi.models import GroupDisplayPermission

from pyscada.models import Log
from pyscada.models import ClientWriteTask

from pyscada import log
#from pyscada.export import timestamp_unix_to_matlab
from django.shortcuts import render
from django.http import HttpResponse
from django.core import serializers
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone
from django.template import Context, loader,RequestContext
from django.db import connection
from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.views.decorators.csrf import requires_csrf_token
import time
import json


@requires_csrf_token
def index(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	
	t = loader.get_template('content.html')
	page_list = Page.objects.filter(groupdisplaypermission__hmi_group__in=request.user.groups.iterator)
	visable_charts_list = Chart.objects.filter(groupdisplaypermission__hmi_group__in=request.user.groups.iterator).values_list('pk',flat=True)

	sliding_panel_list = SlidingPanelMenu.objects.filter(groupdisplaypermission__hmi_group__in=request.user.groups.iterator)
	
	visable_control_element_list = GroupDisplayPermission.objects.filter(hmi_group__in=request.user.groups.iterator).values_list('control_items',flat=True)
	
	panel_list   = sliding_panel_list.filter(position__in=(1,2,))
	control_list = sliding_panel_list.filter(position=0)
	

	c = RequestContext(request,{
		'page_list': page_list,
		'visable_charts_list':visable_charts_list,
		'visable_control_element_list':visable_control_element_list,
		'panel_list': panel_list,
		'control_list':control_list,
		'user': request.user
	})
	log.webnotice('open hmi',request.user)
	return HttpResponse(t.render(c))
	
def config(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	config = {}
	config["DataFile"] 			= "json/data/"
	config["InitialDataFile"] 	= "json/data/"
	config["LogDataFile"] 		= "json/log_data/"
	config["RefreshRate"] 		= 5000
	config["config"] 			= []
	chart_count 				= 0
	charts = GroupDisplayPermission.objects.filter(hmi_group__in=request.user.groups.iterator).values_list('charts',flat=True)
	charts = list(set(charts))
	for chart_id in charts:
		vars = {}
		c_count = 0
		chart = Chart.objects.get(pk=chart_id)
		for var in chart.variables.filter(active=1).order_by('variable_name'):
			color_code = var.variabledisplaypropery.chart_line_color_code()
			if (var.variabledisplaypropery.short_name and var.variabledisplaypropery.short_name != '-'):
				var_label = var.variabledisplaypropery.short_name
			else:
				var_label = var.variable_name
			vars[var.variable_name] = {"yaxis":1,"color":color_code,"unit":var.unit.description,"label":var_label}
			
		config["config"].append({"label":chart.title,"xaxis":{"ticks":chart.x_axis_ticks},"axes":[{"yaxis":{"min":chart.y_axis_min,"max":chart.y_axis_max,'label':chart.y_axis_label}}],"placeholder":"#chart-%d"% chart.pk,"legendplaceholder":"#chart-%d-legend" % chart.pk,"variables":vars}) 
		chart_count += 1		
	
	
	jdata = json.dumps(config,indent=2)
	return HttpResponse(jdata, content_type='application/json')

def log_data(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	if request.POST.has_key('timestamp'):
		timestamp = float(request.POST['timestamp'])
	else:
		timestamp = time.time()-(60*60*24*14) # get log of last 14 days
		
	data = Log.objects.filter(level__gte=6,timestamp__gt=float(timestamp)).order_by('-timestamp')
	odata = []
	for item in data:
		odata.append({"timestamp":item.timestamp,"level":item.level,"message":item.message,"username":item.user.username if item.user else "None"})
	jdata = json.dumps(odata,indent=2)
	
	return HttpResponse(jdata, content_type='application/json')

def form_log_entry(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	if request.POST.has_key('message') and request.POST.has_key('level'):
		log.add(request.POST['message'],request.POST['level'],request.user)
		return HttpResponse(status=200)
	else:
		return HttpResponse(status=404)
	
def	form_write_task(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	if request.POST.has_key('var_id') and request.POST.has_key('value'):
		cwt = ClientWriteTask(variable_id = request.POST['var_id'],value=request.POST['value'],start=time.time(),user=request.user)
		cwt.save()
		return HttpResponse(status=200)
	else:
		return HttpResponse(status=404)

def get_recent_cache_data(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	data = {}
	active_variables = list(GroupDisplayPermission.objects.filter(hmi_group__in=request.user.groups.iterator).values_list('charts__variables',flat=True))
	active_variables += list(GroupDisplayPermission.objects.filter(hmi_group__in=request.user.groups.iterator).values_list('control_items__variable',flat=True))
	active_variables = list(set(active_variables))
	active_variables = list(Variable.objects.filter(id__in=active_variables).values_list('variable_name','id'))
	for var in active_variables:
		if cache.get(var[1]):
			data[var[0]] = cache.get(var[1])
	data['timestamp'] = cache.get('timestamp')*1000
	jdata = json.dumps(data,indent=2)
	return HttpResponse(jdata, content_type='application/json')

def get_cache_data(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	if request.POST.has_key('timestamp'):
		timestamp_from = float(request.POST['timestamp'])
	else:
		timestamp_from = 0
	data = {}
	active_variables = list(GroupDisplayPermission.objects.filter(hmi_group__in=request.user.groups.iterator).values_list('charts__variables',flat=True))
	active_variables += list(GroupDisplayPermission.objects.filter(hmi_group__in=request.user.groups.iterator).values_list('control_items__variable',flat=True))
	active_variables = list(set(active_variables))
	active_variables = list(Variable.objects.filter(id__in=active_variables).values_list('variable_name','id'))
	
	cache_version = cache.get('recent_version')
	while cache_version >= 1 and cache.get('timestamp',None,cache_version) > timestamp_from:
		timestamp = cache.get('timestamp',0,cache_version)*1000
		for var in active_variables:
			if cache.get(var[1],0,cache_version):
				if not data.has_key(var[0]):
					data[var[0]] = []
				data[var[0]].insert(0,[timestamp,cache.get(var[1],0,cache_version)])
		cache_version -= 1
	
	jdata = json.dumps(data,indent=2)
	return HttpResponse(jdata, content_type='application/json')

def data(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	# read POST data
	if request.POST.has_key('timestamp'):
		timestamp = float(request.POST['timestamp'])
	else:
		timestamp = time.time()-(15*60)
	
	# query timestamp pk's
	if not RecordedTime.objects.last():
		return HttpResponse('{\n}', content_type='application/json')
	t_max_pk 		= RecordedTime.objects.last().pk
	rto 			= RecordedTime.objects.filter(timestamp__gte=float(timestamp))
	if rto.count()>0:
		t_min_ts 		= rto.first().timestamp
		t_min_pk 		= rto.first().pk
	else:
		return HttpResponse('{\n}', content_type='application/json')
	
	active_variables = GroupDisplayPermission.objects.filter(hmi_group__in=request.user.groups.iterator).values_list('charts__variables',flat=True)
	active_variables = list(set(active_variables))
	
	data = {}
	
	for var in Variable.objects.filter(value_class__in = ('FLOAT32','SINGLE','FLOAT','FLOAT64','REAL'), pk__in = active_variables):
		var_id = var.pk
		rto = RecordedDataFloat.objects.filter(variable_id=var_id,time_id__lt=t_min_pk).last()
		if rto:
			data[var.variable_name] = [(t_min_ts,rto.value)]
			data[var.variable_name].extend(list(RecordedDataFloat.objects.filter(variable_id=var_id,time_id__range=(t_min_pk,t_max_pk)).values_list('time__timestamp','value')))
		
	for var in Variable.objects.filter(value_class__in = ('INT32','UINT32','INT16','INT','WORD','UINT','UINT16'),pk__in = active_variables):
		var_id = var.pk
		rto = RecordedDataInt.objects.filter(variable_id=var_id,time_id__lt=t_min_pk).last()
		if rto:
			data[var.variable_name] = [(t_min_ts,rto.value)]
			data[var.variable_name].extend(list(RecordedDataInt.objects.filter(variable_id=var_id,time_id__range=(t_min_pk,t_max_pk)).values_list('time__timestamp','value')))
	

	for var in Variable.objects.filter(value_class = 'BOOL', pk__in = active_variables):
		var_id = var.pk
		rto = RecordedDataBoolean.objects.filter(variable_id=var_id,time_id__lt=t_min_pk).last()
		if rto:
			data[var.variable_name] = [(t_min_ts,rto.value)]
			data[var.variable_name].extend(list(RecordedDataBoolean.objects.filter(variable_id=var_id,time_id__range=(t_min_pk,t_max_pk)).values_list('time__timestamp','value')))
	for key in data:
		for idx,item in enumerate(data[key]):
			data[key][idx] = (item[0]*1000,item[1])
	jdata = json.dumps(data,indent=2)
	return HttpResponse(jdata, content_type='application/json')

def logout_view(request):
	logout(request)
	log.webnotice('logout',request.user)
	# Redirect to a success page.
	return redirect('/accounts/login/')

def dataaquisition_daemon_start(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	
	call_command('PyScadaDaemon start')
	return HttpResponse(status=200)
	
def dataaquisition_daemon_stop(request):
	if not request.user.is_authenticated():
		return redirect('/accounts/login/?next=%s' % request.path)
	
	call_command('PyScadaDaemon stop')
	return HttpResponse(status=200)
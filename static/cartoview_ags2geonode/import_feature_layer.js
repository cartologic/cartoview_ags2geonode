/**
 * Created by kamal on 12/8/16.
 */
(function () {
    var app = angular.module('cartoview.ags2geonode', []);
    app.config(function($httpProvider){
        $httpProvider.defaults.xsrfCookieName = 'csrftoken';
        $httpProvider.defaults.xsrfHeaderName = 'X-CSRFToken';
    });
    app.controller('cartoview.ags2geonode.MainController', function ($scope, ImportLayerService) {
        $scope.service = ImportLayerService;
        $scope.getProgressStyle = function () {
            var percent = $scope.service.task.percent || 0
            return {
                width: percent + "%"
            }
        }
    });
    app.service('ImportLayerService', function ($http, $timeout) {
        var service = this;
        this.layer = {};

        this.import = function () {
            service.statusLog = [];
            service.task = null;
            var lastMsg = "";
            service.showMask = true;
            var getState = function (task) {
                service.task = task;
                if(task.message && task.message.msg && lastMsg!=task.message.msg){
                    service.statusLog.push({
                        msg: task.message.msg,
                        status: task.status
                    });
                    lastMsg = task.message.msg;
                }
                if(task.message && task.message.features_count){
                    task.percent = Math.round((task.message.loaded_features / task.message.features_count) * 100)
                }

                if(task.status == "In Progress") {
                    $timeout(function () {
                        $http.get("import/status/?task_id=" + task.id).success(getState)
                    }, 2000);
                }
                else {
                  service.showMask = false;
                }
            };
            $http.post("", this.layer).success(getState)
        };
    });

})();

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
            service.statesLog = [];
            service.task = null;
            var lastMsg = "";
            var getState = function (task) {
                service.task = task;
                if(task.result && task.result.msg && lastMsg!=task.result.msg){
                    service.statesLog.push({
                        msg: task.result.msg,
                        state: task.state
                    });
                    lastMsg = task.result.msg;
                }
                if(task.result && task.result.features_count){
                    task.percent = Math.round((task.result.loaded_features / task.result.features_count) * 100)
                }
                if(task.state != "SUCCESS") {
                    $timeout(function () {
                        $http.get("import/state?task_id=" + task.id).success(getState)
                    }, 2000);
                }
                else{

                }
            };
            $http.post("", this.layer).success(getState)
        };
    });

})();

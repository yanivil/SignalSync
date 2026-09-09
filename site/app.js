(function () {
  var buttons = document.querySelectorAll('.filters button');
  var rows = document.querySelectorAll('#track-table tbody tr');
  function apply(which) {
    rows.forEach(function (row) { row.hidden = which !== 'all' && row.dataset.status !== which; });
    buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.filter === which ? 'true' : 'false'); });
  }
  buttons.forEach(function (b) { b.addEventListener('click', function () { apply(b.dataset.filter); }); });
})();

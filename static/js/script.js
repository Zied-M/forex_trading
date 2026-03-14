document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('sim-form');
    const strategySelect = document.getElementById('strategy');
    const strat2Options = document.getElementById('strat2-options');
    const loading = document.getElementById('loading');
    const btnRun = document.getElementById('btn-run');

    // KPI Elements
    const kpiEquity = document.getElementById('kpi-equity');
    const kpiPnl = document.getElementById('kpi-pnl');
    const kpiWinrate = document.getElementById('kpi-winrate');
    const kpiTrades = document.getElementById('kpi-trades');

    // Chart Instances
    let equityChartInstance = null;
    let predictionChartInstance = null;

    // Toggle Strategy 2 options
    strategySelect.addEventListener('change', (e) => {
        if (e.target.value === '2') {
            strat2Options.classList.remove('hidden');
        } else {
            strat2Options.classList.add('hidden');
        }
    });

    // Form Submit
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // UI State
        btnRun.disabled = true;
        loading.classList.remove('hidden');

        // Gather Data
        const payload = {
            capital: parseFloat(document.getElementById('capital').value),
            start_date: document.getElementById('start_date').value,
            range_hours: parseInt(document.getElementById('range_hours').value),
            strategy: parseInt(strategySelect.value),
            trade_size: parseFloat(document.getElementById('trade_size').value),
            lower: parseFloat(document.getElementById('lower').value),
            upper: parseFloat(document.getElementById('upper').value),
            vol_filter: document.getElementById('vol_filter').checked
        };

        try {
            const response = await fetch('/api/simulate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Simulation failed');
            }

            const data = await response.json();
            updateDashboard(data);

        } catch (error) {
            console.error('Error:', error);
            alert('Error running simulation: ' + error.message);
        } finally {
            btnRun.disabled = false;
            loading.classList.add('hidden');
        }
    });

    function formatCurrency(value) {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
    }

    function updateDashboard(data) {
        // Update KPIs
        const summary = data.summary;
        kpiEquity.textContent = formatCurrency(summary['Final Equity']);
        kpiPnl.textContent = formatCurrency(summary['Total Net PnL']);
        kpiTrades.textContent = summary['Total Trades'].toLocaleString();
        kpiWinrate.textContent = (summary['Win Rate'] * 100).toFixed(1) + '%';

        // Styling for PnL
        kpiPnl.className = 'kpi-value ' + (summary['Total Net PnL'] >= 0 ? 'profit' : 'loss');

        // Render Charts
        renderEquityChart(data.timeseries);
        renderPredictionChart(data.timeseries);
    }

    // Default Chart.js Settings for Dark Mode
    Chart.defaults.color = '#8b949e';
    Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.1)';

    function renderEquityChart(timeseries) {
        const ctx = document.getElementById('equityChart').getContext('2d');

        if (equityChartInstance) {
            equityChartInstance.destroy();
        }

        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, 'rgba(0, 242, 254, 0.4)');
        gradient.addColorStop(1, 'rgba(0, 242, 254, 0.0)');

        equityChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: timeseries.datetime,
                datasets: [{
                    label: 'Portfolio Equity ($)',
                    data: timeseries.equity,
                    borderColor: '#00f2fe',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(22, 27, 34, 0.9)',
                        titleColor: '#fff',
                        bodyColor: '#00f2fe',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1
                    }
                },
                scales: {
                    x: {
                        ticks: { maxTicksLimit: 10 }
                    },
                    y: {
                        ticks: {
                            callback: function (value) {
                                return '$' + value.toLocaleString();
                            }
                        }
                    }
                }
            }
        });
    }

    function renderPredictionChart(timeseries) {
        const ctx = document.getElementById('predictionChart').getContext('2d');

        if (predictionChartInstance) {
            predictionChartInstance.destroy();
        }

        predictionChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: timeseries.datetime,
                datasets: [
                    {
                        type: 'line',
                        label: 'Actual Market Price (Close)',
                        data: timeseries.close,
                        borderColor: '#2ea043',
                        borderWidth: 2,
                        pointRadius: 0,
                        yAxisID: 'y1',
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    tooltip: {
                        backgroundColor: 'rgba(22, 27, 34, 0.9)'
                    }
                },
                scales: {
                    x: {
                        ticks: { maxTicksLimit: 10 }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: { display: true, text: 'Market Price (USD)' }
                    }
                }
            }
        });
    }
});

import matplotlib
from flask import Flask, render_template, request, redirect, url_for
import gpxpy
import gpxpy.gpx
import os
import pandas as pd
from geopy.distance import geodesic
import folium
import matplotlib.pyplot as plt
from dotenv import load_dotenv

matplotlib.use('Agg')

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SAMPLE_FOLDER'] = os.path.join('static', 'sample_gpx_files')
load_dotenv()
MAPBOX_ACCESS_TOKEN = os.getenv('MAPBOX_ACCESS_TOKEN')

def get_sample_files():
    # מקבל את כל שמות הקבצים בתיקייה של הדוגמאות
    return [f for f in os.listdir(app.config['SAMPLE_FOLDER']) if f.endswith('.gpx')]


def parse_gpx(file_path):
    with open(file_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    data = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                # בודק אם קיימים ערכי גובה וזמן, ואם לא, מגדיר אותם כ-None
                elevation = point.elevation if hasattr(point, 'elevation') else None
                time = point.time if hasattr(point, 'time') else None

                data.append({
                    'latitude': point.latitude,
                    'longitude': point.longitude,
                    'elevation': elevation,
                    'time': time
                })

    df = pd.DataFrame(data)

    # בדיקה אם יש עמודת גובה או זמן
    if 'elevation' not in df.columns:
        df['elevation'] = pd.Series([0] * len(df))  # אם אין, מוסיפים עמודת גובה עם ערכים 0
    if 'time' not in df.columns or df['time'].isnull().all():
        df['time'] = pd.Series([None] * len(df))  # אם אין זמן, מוסיפים עמודה עם ערכים ריקים

    # חישוב מרחקים בין נקודות
    df['shifted_latitude'] = df['latitude'].shift(-1)
    df['shifted_longitude'] = df['longitude'].shift(-1)
    df['shifted_time'] = df['time'].shift(-1)

    def calculate_distance(row):
        if pd.notnull(row['shifted_latitude']) and pd.notnull(row['shifted_longitude']):
            start = (row['latitude'], row['longitude'])
            end = (row['shifted_latitude'], row['shifted_longitude'])
            return geodesic(start, end).meters
        return 0

    df['distance'] = df.apply(calculate_distance, axis=1)

    # אם יש זמן, מחשבים מהירות, אחרת מהירות נשארת ריקה
    if not df['time'].isnull().all():
        df['time_diff'] = (df['shifted_time'] - df['time']).dt.total_seconds()
        df['speed'] = df['distance'] / df['time_diff']
    else:
        df['speed'] = pd.Series([None] * len(df))

    df = df.drop(columns=['shifted_latitude', 'shifted_longitude', 'shifted_time'])

    return df


def calculate_features(df):
    total_distance = round(df['distance'].sum() / 1000, 2)  # Total distance in kilometers
    average_speed = round(df['speed'].mean() * 3.6, 2)  # Average speed in km/h
    total_elevation_gain = round(df['elevation'].diff().clip(lower=0).sum(), 2)  # Total elevation gain in meters
    return total_distance, average_speed, total_elevation_gain


def create_map(df):
    # Define the directory within 'static' to save the map
    map_dir = os.path.join('static', 'maps')

    # Ensure the directory exists
    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    # Set up the map with the first coordinate as the center
    m = folium.Map(
        location=[df['latitude'].mean(), df['longitude'].mean()],
        zoom_start=12,
        tiles='https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/{z}/{x}/{y}?access_token=' + MAPBOX_ACCESS_TOKEN,
        attr='Mapbox'
    )

    # Add the route to the map
    folium.PolyLine(
        locations=[(row['latitude'], row['longitude']) for index, row in df.iterrows()],
        color="blue",
        weight=2.5,
        opacity=1
    ).add_to(m)

    # Save the map as an HTML file in the 'static/maps' directory
    map_file_path = os.path.join(map_dir, 'map.html')
    m.save(map_file_path)

    return map_file_path


def create_elevation_plot(df):
    try:
        plt.figure(figsize=(8, 4))
        plt.plot(df['distance'].cumsum() / 1000, df['elevation'], color='gray')
        plt.fill_between(df['distance'].cumsum() / 1000, df['elevation'], color='gray', alpha=0.5)
        plt.xlabel('Distance (km)')
        plt.ylabel('Elevation (m)')
        plt.title('Elevation Profile')
        plt.grid(True)

        # Save the plot as an image file in the static/images directory
        plot_file_path = os.path.join('static', 'images', 'elevation_plot.png')
        plt.savefig(plot_file_path)
        plt.close()

        print(f"Elevation plot saved at: {plot_file_path}")  # Debug output
        return plot_file_path
    except Exception as e:
        print(f"Error creating elevation plot: {e}")
        return None


def create_speed_distribution_plot(df):
    try:
        plt.figure(figsize=(8, 4))
        plt.hist(df['speed'] * 3.6, bins=30, color='blue', alpha=0.7)
        plt.xlabel('Speed (km/h)')
        plt.ylabel('Frequency')
        plt.grid(True)

        # Save the plot as an image file in the static/images directory
        plot_file_path = os.path.join('static', 'images', 'speed_distribution_plot.png')
        plt.savefig(plot_file_path, bbox_inches='tight')
        plt.close()

        print(f"Speed distribution plot saved at: {plot_file_path}")  # Debug output
        return plot_file_path
    except Exception as e:
        print(f"Error creating speed distribution plot: {e}")
        return None


@app.route('/', methods=['GET', 'POST'])
def index():
    sample_files = get_sample_files()

    if request.method == 'POST':
        file_option = request.form['file_option']

        if file_option == 'upload':
            if 'gpxfile' not in request.files:
                return redirect(request.url)
            file = request.files['gpxfile']
            if file.filename == '':
                return redirect(request.url)
            if file:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(file_path)

        elif file_option == 'sample':
            sample_file = request.form['sample_file']
            file_path = os.path.join(app.config['SAMPLE_FOLDER'], sample_file)

        df = parse_gpx(file_path)
        total_distance, average_speed, total_elevation_gain = calculate_features(df)
        map_file_path = create_map(df)
        plot_file_path = create_elevation_plot(df)

        return render_template('results.html', total_distance=total_distance,
                               average_speed=average_speed,
                               total_elevation_gain=total_elevation_gain,
                               map_file_path=map_file_path,
                               plot_file_path=plot_file_path)

    return render_template('index.html', sample_files=sample_files)

if __name__ == '__main__':
    app.run(debug=True)

